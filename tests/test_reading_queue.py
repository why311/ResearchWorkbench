from backend import app as core
from tests.test_workbench import client, create


def material(client, pid, title='待办资料.txt'):
    return client.post(f'/api/projects/{pid}/documents', files={'file': (title, '这是原文段落。用于功能检查，不是正式论文。'.encode())}).json()


def annotate(client, pid, doc, kind='confused', note='如何解释这个设定？'):
    response = client.post(f'/api/projects/{pid}/paper-readings/{doc["id"]}/annotations', json={'span_id': doc['spans'][0]['id'], 'quote': '这是原文段落。', 'kind': kind, 'note': note})
    assert response.status_code == 200
    return response.json()['annotations'][0]


def test_project_queue_and_edit_keep_source(client):
    pid, other = create(client), create(client)
    doc, second = material(client, pid), material(client, pid, '第二篇.txt')
    a = annotate(client, pid, doc)
    annotate(client, pid, second, note='核对随机种子')
    annotate(client, pid, second, kind='highlight', note='普通重点')
    root = f'/api/projects/{pid}/reading-questions'
    queue = client.get(root).json()
    assert queue['total'] == 2 and all(x['kind'] == 'confused' and x['page'] == 1 for x in queue['items'])
    assert client.get(root, params={'q': '随机种子'}).json()['total'] == 1
    assert client.get(root, params={'document_id': second['id'], 'kind': 'all'}).json()['total'] == 2
    assert client.get(f'/api/projects/{other}/reading-questions').json()['total'] == 0
    edit = root + f'/{doc["id"]}/{a["id"]}'
    changed = client.put(edit, json={'kind': 'understood', 'note': '已回看原文并确认。'}).json()
    assert changed['quote'] == a['quote'] and changed['span_id'] == a['span_id'] and changed['created'] == a['created']
    assert client.get(f'/api/projects/{pid}/paper-readings/{doc["id"]}').json()['annotations'][0]['note'] == changed['note']
    assert client.get(root).json()['total'] == 1
    assert client.get(root, params={'kind': 'understood'}).json()['items'][0]['note'] == changed['note']
    assert client.put(f'/api/projects/{other}/reading-questions/{doc["id"]}/{a["id"]}', json={'kind': 'understood'}).status_code == 404
    assert client.put(root + f'/{second["id"]}/{a["id"]}', json={'kind': 'understood'}).status_code == 404
    assert client.put(edit, json={'kind': 'unknown'}).status_code == 422
    assert client.get(root, params={'document_id': material(client, other)['id']}).status_code == 404


def test_queue_pages_and_structured_source_page(client):
    pid = create(client)
    doc = material(client, pid)
    with core.db() as conn:
        conn.execute('INSERT INTO document_blocks VALUES (?,?,?,?,?,?,?,?)', (doc['id'], 'late', 99, 0, 'text', '后页原文', '[]', '{}'))
        for i in range(52):
            conn.execute('INSERT INTO reading_annotations VALUES (?,?,?,?,?,?,?,?,?)', (str(i), pid, doc['id'], 'late', '后页原文', 'confused', f'问题{i}', core.now(), core.now()))
    root = f'/api/projects/{pid}/reading-questions'
    first = client.get(root).json()
    last = client.get(root, params={'offset': 50}).json()
    assert first['total'] == 52 and len(first['items']) == 50 and first['has_more']
    assert all(x['page'] == 99 for x in first['items'])
    assert len(last['items']) == 2 and not last['has_more']
    assert not ({x['id'] for x in first['items']} & {x['id'] for x in last['items']})
    assert client.get(root, params={'q': 'x' * 201}).status_code == 422
    assert client.get(root, params={'offset': -1}).status_code == 422
