import json

from backend import app as core
from tests.test_documents import client, project


def test_source_retrieval_aliases_pagination_and_export(client):
    pid = project(client)
    text = '\n\n'.join([f'Background paragraph about unrelated topic {i}.' for i in range(110)] + ['Random seed 42 controls stochastic reproducibility.'])
    did = client.post(f'/api/projects/{pid}/documents', files={'file': ('source.txt', text.encode())}).json()['id']
    path = f'/api/projects/{pid}/evidence-search'
    data = client.get(path, params={'q': '随机种子'}).json()
    hit = data['items'][0]
    assert hit['text'] == 'Random seed 42 controls stochastic reproducibility.'
    assert hit['id'] == 'p1-s111' and hit['offset'] == 100 and hit['page'] == 1
    assert data['searched_passages'] == 111 and data['searched_documents'] == 1
    original = client.get(f'/api/projects/{pid}/documents/{did}', params={'offset': hit['offset']}).json()
    assert hit['text'] == next(s['text'] for s in original['items'] if s['id'] == hit['id'])
    exported = client.get(path + '/export', params={'q': '随机种子'}).json()
    assert exported == data
    assert client.get(path, params={'q': 'zzzzzzzzzzzzzz'}).json()['items'] == []


def test_search_isolation_validation_and_full_scope_budget(client):
    pid, other = project(client), project(client)
    did = client.post(f'/api/projects/{pid}/documents', files={'file': ('source.txt', b'Exact secret source passage.')}).json()['id']
    assert client.get(f'/api/projects/{other}/evidence-search', params={'q': 'secret'}).json()['items'] == []
    assert client.get(f'/api/projects/{other}/evidence-search', params={'q': 'secret', 'document_id': did}).status_code == 404
    path = f'/api/projects/{pid}/evidence-search'
    assert client.get(path, params={'q': '  '}).status_code == 422
    assert client.get(path, params={'q': 'x' * 201}).status_code == 422
    huge = json.dumps([{'id': f'p1-s{i}', 'page': 1, 'text': 'x' * 1000} for i in range(2001)])
    with core.db() as conn:
        conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?)', ('large', pid, 'Large fixture', 'large.txt', 1, huge))
    assert client.get(path, params={'q': 'secret'}).status_code == 422
    assert client.get(path, params={'q': 'secret', 'document_id': did}).json()['items'][0]['document_id'] == did
