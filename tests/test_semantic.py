import time
import os
from pathlib import Path

import pytest

from backend import app as core, semantic
from tests.test_documents import client, project as create


@pytest.fixture
def local_model(monkeypatch):
    from fastembed import TextEmbedding
    from tokenizers import Tokenizer
    cache = Path(os.environ.get('RESEARCH_TEST_SEMANTIC_CACHE', str(core.ROOT / 'data' / 'semantic-model')))
    if not cache.exists():
        pytest.skip('本机未下载语义模型；本测试不自动联网下载')
    model = TextEmbedding(semantic.MODEL_NAME, cache_dir=str(cache), threads=2, providers=['CPUExecutionProvider'], local_files_only=True)
    tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
    tokenizer.no_truncation(); tokenizer.no_padding()
    monkeypatch.setattr(semantic, 'MODEL', model)
    monkeypatch.setattr(semantic, 'TOKENIZER', tokenizer)
    monkeypatch.setattr(semantic, 'REVISION', model.model._model_dir.name)
    return model


def add_document(pid, title, filename, pages, spans):
    import json
    did = core.uid()
    with core.db() as conn:
        conn.execute('INSERT INTO documents(id,project_id,title,filename,pages,spans) VALUES (?,?,?,?,?,?)',
                     (did, pid, title, filename, pages, json.dumps(spans)))
    return {'id': did}


def wait(client, pid, did):
    for _ in range(300):
        state = client.get(f'/api/projects/{pid}/semantic-indexes').json()
        item = next(i for i in state['indexes'] if i['document_id'] == did)
        if item['status'] not in {'queued', 'running'}:
            assert item['status'] == 'ready', item
            return item
        time.sleep(.05)
    pytest.fail('索引未完成')


def test_real_multilingual_embedding_and_complete_windows(client, local_model, monkeypatch):
    pid, other = create(client), create(client)
    text = 'We describe fruit color and flavor. ' * 100 + 'A random initialization seed is recorded for every repeated run.'
    doc = add_document(pid, 'Long original', 'long.txt', 1, [{'id': 'p1-s1', 'page': 1, 'text': text}, {'id': 'p1-s2', 'page': 1, 'text': 'The telescope collects images of distant galaxies.'}])
    did = doc['id']
    path = f'/api/projects/{pid}'
    assert client.post(path + f'/documents/{did}/semantic-index').status_code == 200
    index = wait(client, pid, did)
    assert index['total'] > 4 and index['completed'] == index['total']
    with core.db() as conn:
        stored = conn.execute('SELECT * FROM semantic_passages WHERE document_id=? AND span_id=? ORDER BY part', (did, 'p1-s1')).fetchall()
    assert stored[0]['text'].startswith('We describe') and stored[-1]['text'].endswith('every repeated run.')
    assert all(r['text'] in text and len(r['vector']) == 384 * 4 for r in stored)
    body = {'question': '怎样记录可重复的随机初始化', 'document_ids': [did], 'hybrid': False}
    result = client.post(path + '/semantic-search', json=body)
    assert result.status_code == 200, result.text
    hit = result.json()['evidence'][0]
    assert hit['id'] == 'p1-s1' and 'random initialization seed' in hit['matched_text']
    assert hit['text'] == text and hit['routes'] == ['semantic'] and hit['citation'] == did + ':p1-s1'
    assert client.post(f'/api/projects/{other}/semantic-search', json=body).status_code == 404
    assert client.post(f'/api/projects/{other}/documents/{did}/semantic-index').status_code == 404
    assert client.get(f'/api/projects/{other}/semantic-indexes').json()['indexes'] == []
    assert client.post(path + '/semantic-search', json={**body, 'question': 'word ' * 190}).status_code == 422
    monkeypatch.setattr(semantic, 'REVISION', 'another-model-version')
    assert client.post(path + '/semantic-search', json=body).status_code == 409
    with core.db() as conn:
        conn.execute('DELETE FROM documents WHERE id=?', (did,))
        assert not conn.execute('SELECT * FROM semantic_passages WHERE document_id=?', (did,)).fetchall()


def test_index_cancel_before_worker_and_unavailable_model(client, local_model, monkeypatch):
    pid = create(client)
    doc = add_document(pid, 'Source', 'source.txt', 1, [{'id': 'p1-s1', 'page': 1, 'text': 'Actual original source.'}])
    path = f'/api/projects/{pid}/documents/{doc["id"]}/semantic-index'
    monkeypatch.setattr(semantic.POOL, 'submit', lambda *_: None)
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409
    assert client.post(path + '/cancel').status_code == 200
    semantic.build(pid, doc['id'])
    assert client.get(f'/api/projects/{pid}/semantic-indexes').json()['indexes'][0]['status'] == 'cancelled'
    monkeypatch.setattr(semantic, 'MODEL', None)
    assert client.post(path).status_code == 409
    assert client.post(f'/api/projects/{pid}/semantic-search', json={'question': 'original', 'document_ids': [doc['id']]}).status_code == 409
