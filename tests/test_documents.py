import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from backend import app as core


@pytest.fixture
def client(tmp_path, monkeypatch):
    with core.db() as conn:
        schema = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")]
    monkeypatch.setattr(core, 'DATA', tmp_path)
    with core.db() as conn:
        for sql in schema:
            conn.execute(sql)
    with TestClient(core.app) as value:
        yield value


def project(client):
    return client.post('/api/projects', json={'name': '文献流程验证', 'question': '按页回查来源'}).json()['id']


def pdf():
    writer = PdfWriter()
    for text in ('First page evidence.', 'Second page conclusion.'):
        page = writer.add_blank_page(612, 792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 50 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_text_original_and_batched_reading(client):
    pid, other = project(client), project(client)
    base = f'/api/projects/{pid}'
    text = '\n\n'.join(f'第{i}段：保留中文原文。' for i in range(107)).encode('utf-8-sig')
    response = client.post(base + '/documents', files={'file': ('研究笔记.md', text)})
    assert response.status_code == 200
    did = response.json()['id']
    assert response.json()['span_count'] == 107
    assert client.get(base).json()['documents'][0]['filename'] == '研究笔记.md'
    first = client.get(base + f'/documents/{did}').json()
    last = client.get(base + f'/documents/{did}?offset=100').json()
    assert len(first['items']) == 100 and first['has_more']
    assert len(last['items']) == 7 and not last['has_more']
    assert first['items'][0]['id'] == 'p1-s1'
    assert client.get(base + f'/documents/{did}/original').content == text
    assert client.get(f'/api/projects/{other}/documents/{did}').status_code == 404
    assert client.get(f'/api/projects/{other}/documents/{did}/original').status_code == 404
    assert client.get(base + f'/documents/{did}?page=2').status_code == 422
    assert client.get(base + f'/documents/{did}?offset=-1').status_code == 422


def test_pdf_keeps_page_locations(client):
    pid = project(client)
    base = f'/api/projects/{pid}/documents'
    response = client.post(base, files={'file': ('paper.pdf', pdf())})
    assert response.status_code == 200
    did = response.json()['id']
    assert response.json()['pages'] == 2
    assert 'First page' in client.get(base + '/' + did).json()['items'][0]['text']
    second = client.get(base + '/' + did + '?page=2').json()
    assert second['items'][0]['page'] == 2 and 'Second page' in second['items'][0]['text']


def test_invalid_uploads_and_origins(client):
    base = f'/api/projects/{project(client)}/documents'
    for name, content in [('x.pdf', b'broken'), ('x.docx', b'no'), ('x.txt', b'  '), ('x.txt', b'\xff')]:
        assert client.post(base, files={'file': (name, content)}).status_code == 422
    assert client.post(base, files={'file': ('x.txt', b'x' * (20 * 1024 * 1024 + 1))}).status_code == 413
    for origin in ('https://example.com', 'http://localhost:bad', 'null'):
        assert client.post('/api/projects', headers={'Origin': origin}, json={'name': '拒绝跨站请求'}).status_code == 403
    assert client.post('/api/projects', headers={'Origin': 'http://localhost:5178'}, json={'name': '本地开发'}).status_code == 200
