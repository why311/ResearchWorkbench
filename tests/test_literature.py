import io
import json
import zipfile

from backend import app as core
from backend import literature
from tests.test_workbench import client, create


def add(pid):
    return core.add_document(pid, 'Source fixture', 'fixture.txt', 3, [
        {'id': 'p1-s1', 'page': 1, 'text': 'We use random seed 42. Main text mentions doi:10.9999/body.'},
        {'id': 'p2-s1', 'page': 2, 'text': 'References\n[1] Example title. https://doi.org/10.1234/ABC(2).\n[2] Model. arXiv:2301.12345v2.'},
        {'id': 'p3-s1', 'page': 3, 'text': 'Additional notes. Random seed 7.'}])


def test_manual_translation_paging_export_and_boundaries(client):
    pid, other = create(client), create(client)
    doc = add(pid)
    base = f'/api/projects/{pid}/documents/{doc["id"]}'
    original = client.get(base + '/translations?page=3').json()
    assert original['items'][0]['id'] == 'p3-s1' and original['items'][0]['translation'] is None
    value = {'language': 'zh', 'text': '<script>bad()</script> 附加说明。随机种子为7。', 'reviewed': True}
    assert client.put(base + '/translations/p3-s1', json=value).status_code == 200
    saved = client.get(base + '/translations?page=3').json()['items'][0]
    assert saved['translation']['reviewed'] and saved['translation']['method'] == 'manual'
    assert client.get(base + '/translations?language=en&page=3').json()['items'][0]['translation'] is None
    assert client.put(base + '/translations/missing', json=value).status_code == 404
    assert client.put(base + '/translations/p3-s1', json={**value, 'text': '  '}).status_code == 422
    assert client.get(base + '/translations?page=4').status_code == 422
    other_base = f'/api/projects/{other}/documents/{doc["id"]}'
    assert client.get(other_base + '/translations').status_code == 404
    assert client.put(other_base + '/translations/p3-s1', json=value).status_code == 404
    assert client.get(other_base + '/translations-export').status_code == 404
    archive = zipfile.ZipFile(io.BytesIO(client.get(base + '/translations-export').content))
    exported = json.loads(archive.read('sources.json'))['translations']
    assert len(exported) == 1 and exported[0]['source']['page'] == 3
    offline = archive.read('bilingual.html').decode()
    assert '<script>' not in offline and '&lt;script&gt;' in offline
    assert '随机种子为7' in archive.read('bilingual.md').decode()
    client.delete(f'/api/projects/{pid}/documents/{doc["id"]}')
    with core.db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM translations').fetchone()[0] == 0


def test_model_alignment_scope_and_manual_save_wins(client, monkeypatch):
    pid = create(client)
    doc = core.add_document(pid, 'Two passages', 'two.txt', 1, [
        {'id': 'p1-s1', 'page': 1, 'text': 'Random seed 42.'},
        {'id': 'p1-s2', 'page': 1, 'text': 'GPU V100.'}])
    did = doc['id']
    base = f'/api/projects/{pid}/documents/{did}'
    captured = []
    def model(instruction, material):
        captured.append(json.loads(material))
        # A user saves a correction while the model request is in flight.
        literature.save_translation(pid, did, 'p1-s1', literature.TranslationBody(text='作者填写种子42', reviewed=True))
        return {'translations': [
            {'span_id': 'p1-s1', 'source': 'Random seed 42.', 'translation': '模型种子42'},
            {'span_id': 'p1-s2', 'source': 'GPU A100.', 'translation': '错误原文对应'},
            {'span_id': 'unknown', 'source': 'Unknown', 'translation': '伪造'}]}
    monkeypatch.setattr(core, 'model_json', model)
    result = client.post(base + '/translate', json={'page': 1}).json()
    assert result['warnings'] and result['items'][0]['translation']['text'] == '作者填写种子42'
    assert result['items'][0]['translation']['reviewed'] and result['items'][1]['translation'] is None
    assert len(captured[0]) == 2
    def second_model(_, material):
        assert [s['span_id'] for s in json.loads(material)] == ['p1-s2']
        return {'translations': [{'span_id': 'p1-s2', 'source': 'GPU V100.', 'translation': '使用V100 GPU。'}]}
    monkeypatch.setattr(core, 'model_json', second_model)
    result = client.post(base + '/translate', json={'page': 1}).json()
    assert result['items'][1]['translation']['method'] == 'model' and not result['items'][1]['translation']['reviewed']
    assert client.post(base + '/translate', json={'page': 1}).status_code == 409


def test_translation_missing_model_invalid_output_and_budgets(client, monkeypatch):
    pid = create(client)
    doc = add(pid)
    base = f'/api/projects/{pid}/documents/{doc["id"]}'
    assert client.post(base + '/translate', json={'page': 3}).status_code == 409
    monkeypatch.setattr(core, 'model_json', lambda *_: {'translations': [{'span_id': 'p1-s1', 'source': 'not matching', 'translation': 'bad'}]})
    assert client.post(base + '/translate', json={'page': 1}).status_code == 502
    assert client.get(base + '/translations').json()['items'][0]['translation'] is None
    large = core.add_document(pid, 'Large', 'large.txt', 1, [{'id': 'p1-s1', 'page': 1, 'text': 'A' * 21000}])
    assert client.post(f'/api/projects/{pid}/documents/{large["id"]}/translate', json={'page': 1}).status_code == 422
    assert client.post(base + '/translate', json={'page': 4}).status_code == 422


def test_reference_candidates_confirm_link_export_and_project_isolation(client):
    pid, other = create(client), create(client)
    doc, target, foreign = add(pid), add(pid), add(other)
    base = f'/api/projects/{pid}'
    endpoint = base + f'/documents/{doc["id"]}/references-extract'
    result = client.post(endpoint, json={'start_page': 2, 'end_page': 2}).json()
    assert result['created'] == 2 and result['found'] == 2
    network = client.get(base + '/reference-network').json()
    rows = network['references']
    assert {r['identifier'] for r in rows} == {'doi:10.1234/abc(2)', 'arxiv:2301.12345'}
    assert all(r['status'] == 'candidate' and r['span_id'] == 'p2-s1' for r in rows)
    assert all(r['quote'] in doc['spans'][1]['text'] for r in rows)
    rid = rows[0]['id']
    value = {'label': 'Named referenced paper', 'status': 'confirmed', 'target_document_id': target['id']}
    assert client.put(base + '/references/' + rid, json={**value, 'target_document_id': foreign['id']}).status_code == 404
    assert client.put(base + '/references/' + rid, json={**value, 'target_document_id': doc['id']}).status_code == 422
    assert client.put(base + '/references/' + rid, json=value).json()['status'] == 'confirmed'
    assert client.post(endpoint, json={'start_page': 2, 'end_page': 2}).json()['created'] == 0
    exported = client.get(base + '/reference-network/export').json()
    kept = next(r for r in exported['references'] if r['id'] == rid)
    assert kept['target_document_id'] == target['id'] and kept['status'] == 'confirmed'
    assert client.get(f'/api/projects/{other}/reference-network').json()['references'] == []
    assert client.put(f'/api/projects/{other}/references/{rid}', json=value).status_code == 404
    assert client.delete(f'/api/projects/{other}/references/{rid}').status_code == 404
    assert client.post(f'/api/projects/{other}/documents/{doc["id"]}/references-extract', json={'start_page': 2, 'end_page': 2}).status_code == 404
    client.delete(base + f'/documents/{target["id"]}')
    assert next(r for r in client.get(base + '/reference-network').json()['references'] if r['id'] == rid)['target_document_id'] is None
    assert client.delete(base + '/references/' + rid).status_code == 200
    client.delete(base + f'/documents/{doc["id"]}')
    assert not client.get(base + '/reference-network').json()['references']


def test_reference_range_and_identifier_edges(client):
    pid = create(client)
    doc = add(pid)
    path = f'/api/projects/{pid}/documents/{doc["id"]}/references-extract'
    assert client.post(path, json={'start_page': 3, 'end_page': 1}).status_code == 422
    assert client.post(path, json={'start_page': 1, 'end_page': 4}).status_code == 422
    assert client.post(path, json={'start_page': 3, 'end_page': 3}).json()['found'] == 0
    parsed = literature.identifiers('doi:10.1234/Title(2)). arxiv.org/abs/hep-th/9901001v3; arXiv:2301.12345v5')
    assert [r[0] for r in parsed] == ['doi:10.1234/title(2)', 'arxiv:hep-th/9901001', 'arxiv:2301.12345']
