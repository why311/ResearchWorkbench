import time

from backend import app as core
from backend import assistant
from tests.test_documents import client, project as create


def add(client, pid, name, text):
    response = client.post(f'/api/projects/{pid}/documents', files={'file': (name + '.md', text.encode())})
    assert response.status_code == 200
    doc = response.json()
    page = client.get(f'/api/projects/{pid}/documents/{doc["id"]}').json()
    return {**doc, 'spans': page['items']}


def task(client, pid, docs, kind='comparison', **extra):
    response = client.post(f'/api/projects/{pid}/research-tasks', json={'kind': kind, 'intent': '比较随机种子与硬件环境，列出复现前的待确认条件', 'document_ids': [d['id'] for d in docs], 'fields': ['随机种子', '硬件环境'], **extra})
    assert response.status_code == 200, response.text
    tid = response.json()['id']
    for _ in range(200):
        result = client.get(f'/api/projects/{pid}/research-tasks/{tid}').json()
        if result['status'] not in {'running', 'queued'}:
            return result
        time.sleep(.05)
    raise AssertionError('Research task timeout')


def test_local_comparison_and_observable_tools(client):
    pid = create(client)
    a = add(client, pid, 'A', 'Training uses random seed 42.\n\nWe use one NVIDIA V100 GPU.')
    b = add(client, pid, 'B', 'Random seed is 7.\n\nAll runs use CPU hardware.')
    result = task(client, pid, [a, b], 'agent')
    assert result['status'] == 'completed' and result['mode'] == 'local'
    assert [s['tool'] for s in result['steps']] == ['inspect_documents', 'compare_papers', 'prepare_reproduction', 'finish']
    rows = result['result']['comparison']['rows']
    assert len(rows) == 2 and all(c['status'] == 'evidence_only' for r in rows for c in r['cells'])
    assert all(e['document_id'] == r['document_id'] for r in rows for c in r['cells'] for e in c['evidence'])
    assert '未启用模型自主规划' in result['result']['note']
    assert result['result']['checklist'] and not result['result']['claims']
    exported = client.get(f'/api/projects/{pid}/research-tasks/{result["id"]}/export?format=csv')
    assert 'seed 42' in exported.content.decode('utf-8-sig') and 'V100' in exported.text
    assert client.get(f'/api/projects/{pid}/research-tasks/{result["id"]}/export').json()['steps']
    endpoint = f'/api/projects/{pid}/research-tasks/{result["id"]}/research-note'
    first, again = client.post(endpoint).json(), client.post(endpoint).json()
    assert first['created'] and not again['created'] and first['id'] == again['id']
    note = client.get(f'/api/projects/{pid}/research-notes/{first["id"]}').json()
    assert note['outcome'] == 'planned' and note['sources'] and not note['run_ids']
    assert client.post(f'/api/projects/{create(client)}/research-tasks/{result["id"]}/research-note').status_code == 404


def test_model_extraction_rejects_fake_and_cross_document_quotes(client, monkeypatch):
    pid = create(client)
    a = add(client, pid, 'A', 'Random seed 42. Hardware NVIDIA V100 GPU.')
    b = add(client, pid, 'B', 'Random seed 7. Hardware CPU.')
    source = a['id'] + ':' + a['spans'][0]['id']
    def model(instruction, material):
        if source in material:
            return {'cells': [{'field': '随机种子', 'value': '42', 'citation': source, 'quote': 'Random seed 42.'},
                {'field': '硬件环境', 'value': '128个A100', 'citation': source, 'quote': '128 A100 GPUs'}]}
        return {'cells': [{'field': '随机种子', 'value': '42', 'citation': source, 'quote': 'Random seed 42.'}]}
    monkeypatch.setattr(core, 'model_json', model)
    result = task(client, pid, [a, b])
    assert result['status'] == 'completed'
    rows = result['result']['comparison']['rows']
    assert rows[0]['cells'][0]['status'] == 'quote_checked' and rows[0]['cells'][0]['value'] == '42'
    assert rows[0]['cells'][1]['status'] == 'unverified' and '128个A100' not in str(rows)
    assert rows[1]['cells'][0]['status'] == 'unverified'


def test_function_calling_observes_output_and_checks_final_claims(client, monkeypatch):
    pid = create(client)
    a = add(client, pid, 'A', 'Random seed 42. Hardware NVIDIA V100 GPU.')
    citation = a['id'] + ':' + a['spans'][0]['id']
    monkeypatch.setattr(core, 'settings', lambda: {'base_url': 'http://localhost:9999/v1', 'model': 'test', 'api_key': ''})
    calls = []
    def choose(messages):
        calls.append(messages.copy())
        if len(calls) == 1:
            return {'name': 'search_evidence', 'arguments': {'query': '随机种子 seed'}, 'call_id': 'call1'}
        assert messages[-1]['role'] == 'tool' and 'seed 42' in messages[-1]['content']
        return {'name': 'finish', 'arguments': {'claims': [{'text': '材料写明种子42，仍需核对代码。', 'citation': citation, 'quote': 'Random seed 42.'},
            {'text': '伪造的结果', 'citation': citation, 'quote': 'Not a real quote'}]}, 'call_id': 'call2'}
    monkeypatch.setattr(assistant, 'choose_tool', choose)
    result = task(client, pid, [a], 'agent')
    assert result['mode'] == 'function_calling' and result['status'] == 'completed'
    assert len(result['result']['claims']) == 1 and result['steps'][0]['output'][0]['citation'] == citation
    assert '伪造的结果' not in str(result['result'])


def test_task_boundaries_and_cancel(client, monkeypatch):
    pid, other = create(client), create(client)
    a = add(client, pid, 'A', 'Random seed 42.')
    monkeypatch.setattr(assistant.POOL, 'submit', lambda *_: None)
    response = client.post(f'/api/projects/{pid}/research-tasks', json={'intent': '比较设置', 'document_ids': [a['id']], 'fields': ['随机种子']})
    tid = response.json()['id']
    assert client.get(f'/api/projects/{other}/research-tasks/{tid}').status_code == 404
    assert client.get(f'/api/projects/{other}/research-tasks/{tid}/export').status_code == 404
    assert client.post(f'/api/projects/{other}/research-tasks', json={'intent': '比较设置', 'document_ids': [a['id']]}).status_code == 404
    assert client.post(f'/api/projects/{pid}/research-tasks/{tid}/cancel').json()['status'] == 'cancelled'
    assert client.post(f'/api/projects/{pid}/research-tasks', json={'intent': '比较设置', 'document_ids': [a['id'], a['id']]}).status_code == 422
