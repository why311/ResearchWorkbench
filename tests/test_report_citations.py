import io
import json
import zipfile

from docx import Document

from backend import app as core
from tests.test_workbench import client, create


def source(client, pid, name='文献来源.txt'):
    response = client.post(f'/api/projects/{pid}/documents', files={'file': (name, '方法采用标准化。\n\n评价结果需与数据划分一同解释。'.encode())})
    assert response.status_code == 200, response.text
    return client.get(f'/api/projects/{pid}').json()['documents'][0]


def test_citation_numbering_and_saved_exports(client):
    pid = create(client)
    doc = source(client, pid)
    a, b = doc['spans'][:2]
    body = {'title': '文献依据验证', 'template': '先讨论评价[[cite:evaluation]]，再讨论方法[[cite:method]]，重复评价[[cite:evaluation]]。',
            'citations': [{'alias': 'method', 'document_id': doc['id'], 'span_id': a['id']}, {'alias': 'evaluation', 'document_id': doc['id'], 'span_id': b['id']}]}
    report = client.post(f'/api/projects/{pid}/reports', json=body).json()
    base = f'/api/projects/{pid}/reports/{report["id"]}'
    generated = client.post(base + '/generate').json()
    assert generated['sync_status'] == 'synced'
    sources = client.get(base + '/artifacts/sources.json').json()['citations']
    assert [s['alias'] for s in sources] == ['evaluation', 'method']
    assert sources[0]['number'] == 1 and sources[0]['text'] == b['text'] and sources[0]['page'] == 1
    md = client.get(base + '/artifacts/report.md').text
    assert '先讨论评价[1]，再讨论方法[2]，重复评价[1]' in md
    assert '文献原文依据' in md and a['text'] in md and doc['id'] in md
    word = client.get(base + '/word')
    assert word.status_code == 200
    text = '\n'.join(p.text for p in Document(io.BytesIO(word.content)).paragraphs)
    assert '评价[1]' in text and a['text'] in text and '第1页' in text
    # Removing original material invalidates a new generation but never rewrites saved outputs.
    assert client.delete(f'/api/projects/{pid}/documents/{doc["id"]}').status_code == 200
    current = client.get(base).json()
    assert current['sync_status'] == 'invalid'
    assert client.post(base + '/generate').status_code == 422
    assert client.get(base + '/artifacts/report.md').text == md
    assert a['text'] in '\n'.join(p.text for p in Document(io.BytesIO(client.get(base + '/word').content)).paragraphs)
    archive = zipfile.ZipFile(io.BytesIO(client.get(base + '/export').content))
    assert json.loads(archive.read('sources.json'))['citations'] == sources
    client.put(base, json={'title': '移除文献后的草稿', 'template': '无引用'})
    assert client.post(base + '/generate').json()['generated']['version'] == 2
    assert '文献原文依据' not in client.get(base + '/artifacts/report.md').text


def test_invalid_references_and_unknown_tokens(client):
    pid, other = create(client), create(client)
    doc = source(client, other)
    reference = {'alias': 'paper', 'document_id': doc['id'], 'span_id': doc['spans'][0]['id']}
    path = f'/api/projects/{pid}/reports'
    assert client.post(path, json={'title': '跨项目', 'citations': [reference]}).status_code == 422
    own = source(client, pid)
    reference.update(document_id=own['id'], span_id='missing')
    assert client.post(path, json={'title': '缺失片段', 'citations': [reference]}).status_code == 422
    reference['span_id'] = own['spans'][0]['id']
    assert client.post(path, json={'title': '重名', 'citations': [reference, reference]}).status_code == 422
    r = client.post(path, json={'title': '未绑定', 'template': '见[[cite:unknown]]'}).json()
    assert r['sync_status'] == 'invalid'
    assert client.post(path + '/' + r['id'] + '/generate').status_code == 422


def test_structured_later_page_and_literal_source_text(client):
    pid = create(client)
    doc = source(client, pid)
    quote = 'Source says $not_math$ and ![external](https://example.com/a.png).'
    with core.db() as conn:
        conn.execute('UPDATE documents SET pages=99 WHERE id=?', (doc['id'],))
        conn.execute('INSERT INTO document_blocks VALUES (?,?,?,?,?,?,?,?)', (doc['id'], 'p99-s1', 99, 0, 'text', quote, '[]', '{}'))
    r = client.post(f'/api/projects/{pid}/reports', json={'title': '末页原文', 'template': '按原文核对[[cite:later]]。', 'citations': [{'alias': 'later', 'document_id': doc['id'], 'span_id': 'p99-s1'}]}).json()
    base = f'/api/projects/{pid}/reports/{r["id"]}'
    generated = client.post(base + '/generate').json()
    assert generated['state']['citations'][0]['page'] == 99
    word = client.get(base + '/word')
    assert word.status_code == 200
    text = '\n'.join(p.text for p in Document(io.BytesIO(word.content)).paragraphs)
    assert quote in text and '第99页' in text
    archive = zipfile.ZipFile(io.BytesIO(word.content))
    assert b'TargetMode="External"' not in archive.read('word/_rels/document.xml.rels')
