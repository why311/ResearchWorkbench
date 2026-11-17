import io
import json
import zipfile

from backend import app as core
from tests.test_workbench import client, create


def upload(client, pid, text='方法采用标准化处理。\n\n没有预先给出运行结果，需实际执行。'):
    response = client.post(f'/api/projects/{pid}/documents', files={'file': ('reading.md', text.encode('utf-8'))})
    assert response.status_code == 200, response.text
    return response.json()


def entry(span_id, **extra):
    return {'id': 'entry-test', 'section': 'bench', 'title': '标准化的作用需要同划分对照',
        'body': '固定划分比较开启和关闭标准化；尚未实际执行。', 'grade': 'inferred',
        'span_ids': [span_id], 'rationale': '原文给出预处理但没有实验值。',
        'diagnostic': '固定其他设置，观察每个种子的accuracy差值。', 'cost': '额外运行两组方案，需核对数据泄漏。', **extra}


def test_saved_reading_annotations_handoff_and_safe_export(client):
    pid = create(client)
    doc = upload(client, pid, '<script>alert(1)</script>\n\n方法采用标准化处理。')
    did, sid = doc['id'], doc['spans'][1]['id']
    path = f'/api/projects/{pid}/paper-readings/{did}'
    assert doc['has_original']
    assert client.get(f'/api/projects/{pid}/documents/{did}/original').content.decode() == '<script>alert(1)</script>\n\n方法采用标准化处理。'
    body = {'goal': 'reproduce', 'entries': [entry(sid), entry(sid, id='entry-script', section='math', body=r'<img src=x onerror=alert(1)> $z=(x-\mu)/\sigma$')]}
    saved = client.put(path, json=body)
    assert saved.status_code == 200, saved.text
    quote = doc['spans'][1]['text']
    annotation = {'span_id': sid, 'quote': quote, 'kind': 'confused', 'note': '标准化统计量是否只由训练集计算？'}
    annotated = client.post(path + '/annotations', json=annotation).json()
    assert annotated['annotations'][0]['quote'] == quote
    aid = annotated['annotations'][0]['id']
    assert client.post(path + '/annotations', json={**annotation, 'quote': '不在原文的引文'}).status_code == 422
    first = client.post(path + '/entries/entry-test/research-note').json()
    again = client.post(path + '/entries/entry-test/research-note').json()
    assert first['created'] and not again['created'] and first['id'] == again['id']
    note = client.get(f'/api/projects/{pid}/research-notes/{first["id"]}').json()
    assert note['outcome'] == 'planned' and not note['run_ids']
    assert note['source_refs'] == [{'document_id': did, 'span_id': sid}]
    assert '固定其他设置' in note['prediction'] and '尚未执行验证' in note['decision']
    # Editing the text must not clear an existing handoff link.
    client.put(path, json=body)
    assert client.get(path).json()['entries'][0]['note_id'] == first['id']
    kept = client.get(path).json()['entries']
    assert client.put(path, json={'goal': 'reproduce', 'entries': kept[1:]}).status_code == 200
    assert client.put(path, json={'goal': 'reproduce', 'entries': kept}).status_code == 200
    assert not client.post(path + '/entries/entry-test/research-note').json()['created']
    invalid = {**kept[0], 'note_id': 'missing-note'}
    assert client.put(path, json={'goal': 'reproduce', 'entries': [invalid]}).status_code == 422
    response = client.get(path + '/export')
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {'reading.md', 'reading.html', 'sources.json'} == set(archive.namelist())
    sources = json.loads(archive.read('sources.json'))
    assert sources['annotations'][0]['kind'] == 'confused'
    assert sources['source_spans'][0]['id'] == sid
    html = archive.read('reading.html').decode()
    assert '<img src=x' not in html and '&lt;img' in html
    removed = client.delete(path + '/annotations/' + aid)
    assert removed.status_code == 200
    assert not client.get(path).json()['annotations']
    assert client.post(path + '/annotations', json=removed.json()).status_code == 200


def test_model_quotes_coverage_feedback_and_existing_notes(client, monkeypatch):
    pid = create(client)
    doc = upload(client, pid)
    did, sid = doc['id'], doc['spans'][0]['id']
    path = f'/api/projects/{pid}/paper-readings/{did}'
    client.put(path, json={'entries': [entry(sid)]})
    client.post(path + '/annotations', json={'span_id': sid, 'quote': '方法采用标准化处理。', 'kind': 'understood', 'note': ''})
    client.post(path + '/annotations', json={'span_id': sid, 'quote': '标准化', 'kind': 'confused', 'note': '均值来自哪里？'})
    captured = {}
    def model(instruction, material):
        captured.update(instruction=instruction, material=material)
        return {'entries': [
            {'section': 'mechanism', 'title': '已核对来源', 'body': '文中使用标准化。', 'grade': 'stated', 'span_ids': [sid], 'quotes': ['方法采用标准化处理。']},
            {'section': 'experiments', 'title': '伪造的引用不作为事实', 'body': '声称获得99.9%的提升。', 'grade': 'stated', 'span_ids': [sid], 'quotes': ['不存在的实验结果']},
            {'section': 'insight', 'title': '未知位置', 'body': '模型的未验证解释。', 'grade': 'stated', 'span_ids': ['unknown'], 'quotes': ['虚构']}
        ]}
    monkeypatch.setattr(core, 'model_json', model)
    result = client.post(path + '/generate', json={'goal': 'math', 'start_page': 1, 'end_page': 1})
    assert result.status_code == 200, result.text
    generated = result.json()
    assert generated['saved'] and generated['coverage']['feedback_count'] == 2
    assert len(generated['entries']) == 4 and generated['entries'][0]['id'] == 'entry-test'
    assert generated['entries'][1]['grade'] == 'stated'
    assert generated['entries'][2]['grade'] == 'speculative' and generated['entries'][3]['span_ids'] == []
    assert generated['warnings']
    assert '已懂' in captured['material'] and '不懂' in captured['material'] and '均值来自哪里' in captured['material']
    assert '最多18条' in captured['instruction'] and '只使用本次页范围' in captured['instruction']
    assert client.get(path).json()['goal'] == 'math'
    assert client.get(path).json()['coverage']['characters'] > 0


def test_scope_limits_no_model_and_project_boundaries(client, monkeypatch):
    pid, other = create(client), create(client)
    doc = upload(client, pid)
    did, sid = doc['id'], doc['spans'][0]['id']
    path = f'/api/projects/{pid}/paper-readings/{did}'
    assert client.get(f'/api/projects/{other}/paper-readings/{did}').status_code == 404
    assert client.get(f'/api/projects/{other}/documents/{did}/original').status_code == 404
    assert client.put(path, json={'entries': [entry('unknown')]}).status_code == 422
    assert client.put(path, json={'entries': [entry(sid, grade='stated', span_ids=[])]}).status_code == 422
    assert client.put(path, json={'entries': [entry(sid), entry(sid)]}).status_code == 422
    assert client.post(path + '/generate', json={'start_page': 1, 'end_page': 2}).status_code == 422
    assert client.post(path + '/generate', json={'start_page': 1, 'end_page': 1}).status_code == 409
    assert not client.get(path).json()['entries']
    large = core.add_document(pid, '较长的两页资料', 'large.txt', 2, [
        {'id': 'p1-s1', 'page': 1, 'text': 'A' * 40000}, {'id': 'p2-s2', 'page': 2, 'text': 'B' * 40000}])
    large_path = f'/api/projects/{pid}/paper-readings/{large["id"]}'
    assert client.post(large_path + '/generate', json={'start_page': 1, 'end_page': 2}).status_code == 422
    captured = []
    def model(_, material):
        captured.append(material)
        return {'entries': [{'section': 'limits', 'title': '范围内未找到', 'body': '当前选择页未找到相应描述。', 'grade': 'unreported', 'span_ids': []}]}
    monkeypatch.setattr(core, 'model_json', model)
    scoped = client.post(large_path + '/generate', json={'start_page': 1, 'end_page': 1})
    assert scoped.status_code == 200 and scoped.json()['coverage']['end_page'] == 1
    assert 'B' * 100 not in captured[0] and 'A' * 40000 in captured[0]
    # Ordinary foreign-key cascades remove reading metadata with the document.
    client.put(path, json={'entries': [entry(sid)]})
    client.post(path + '/annotations', json={'span_id': sid, 'quote': doc['spans'][0]['text'], 'kind': 'highlight'})
    client.delete(f'/api/projects/{pid}/documents/{did}')
    with core.db() as db:
        assert db.execute('SELECT COUNT(*) FROM paper_readings WHERE document_id=?', (did,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM reading_annotations WHERE document_id=?', (did,)).fetchone()[0] == 0
