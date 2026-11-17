import io
import json
import sqlite3
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend import app as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    old_db = module.DB
    with sqlite3.connect(old_db) as source:
        schema = '\n'.join(row[0] for row in source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'DB', tmp_path / 'test.sqlite3')
    with module.db() as conn:
        for sql in schema.split('CREATE TABLE'):
            if sql.strip():
                conn.execute('CREATE TABLE' + sql)
    monkeypatch.setattr(module, 'model_json', lambda *_: None)
    with TestClient(module.app) as client:
        yield client


def create(client):
    response = client.post('/api/projects', json={'name': '测试研究', 'question': '标准化是否改变Iris分类结果？'})
    assert response.status_code == 200
    return response.json()['id']


def test_document_evidence_matrix_and_export(client):
    pid = create(client)
    assert client.post(f'/api/projects/{pid}/demo').status_code == 200
    response = client.post(f'/api/projects/{pid}/evidence', json={'question': '评价指标 Accuracy Macro F1'})
    data = response.json()
    assert data['evidence'] and not data['claims']
    for span in data['evidence']:
        assert span['page'] == 1 and span['citation'].endswith(span['id'])
    response = client.post(f'/api/projects/{pid}/matrix')
    assert response.status_code == 200
    doc = response.json()[0]
    for key in module.MATRIX_FIELDS:
        assert doc['matrix'][key]['span_id'] in {s['id'] for s in doc['spans']}
    response = client.put(f'/api/projects/{pid}/documents/{doc["id"]}/matrix', json={'method': '作者修订的方法'})
    assert response.status_code == 200
    proposal = client.get(f'/api/projects/{pid}/export/proposal.md').text
    assert '作者修订的方法' in proposal and '第1页' in proposal and '作者已核对' in proposal
    assert '作者修订的方法' in client.get(f'/api/projects/{pid}/export/matrix.csv').text
    assert client.delete(f'/api/projects/{pid}/documents/{doc["id"]}').status_code == 200
    assert client.post(f'/api/projects/{pid}/evidence', json={'question': 'Iris'}).json()['evidence'] == []


def test_actual_experiment_and_rerun_bundle(client):
    pid = create(client)
    run = client.post(f'/api/projects/{pid}/runs', json={'name': '实际实验', 'standardize': True}).json()
    for _ in range(60):
        record = client.get(f'/api/projects/{pid}/runs/{run["id"]}').json()
        if record['status'] not in {'running', 'queued'}:
            break
        time.sleep(.25)
    assert record['status'] == 'succeeded', record['log']
    assert 0 <= record['metrics']['accuracy'] <= 1
    assert record['metrics']['test_samples'] == 45
    assert 'Loaded sklearn Iris' in record['log']
    assert 'confusion.png' in record['artifacts']
    assert 'environment.json' in record['artifacts']
    image = client.get(f'/api/projects/{pid}/runs/{run["id"]}/artifacts/confusion.png')
    assert image.content.startswith(b'\x89PNG')
    bundle = client.get(f'/api/projects/{pid}/export/reproduction.zip')
    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    assert f'runs/{run["id"]}/metrics.json' in archive.namelist()
    assert 'builtin/experiment.py' in archive.namelist()
    assert json.loads(archive.read(f'runs/{run["id"]}/metrics.json')) == record['metrics']
    assert '不是已发表论文的完整复现' in archive.read('复现说明.md').decode()


def test_untrusted_inputs_and_project_boundaries(client):
    pid, other = create(client), create(client)
    text = '## 方法\n真实方法\n\n## 数据\n数据集Iris'
    doc = client.post(f'/api/projects/{pid}/documents', files={'file': ('paper.md', text.encode(), 'text/plain')}).json()
    assert client.put(f'/api/projects/{other}/documents/{doc["id"]}/matrix', json={'method': 'wrong'}).status_code == 404
    assert client.post(f'/api/projects/{pid}/repositories', json={'url': 'http://127.0.0.1/private'}).status_code == 422
    assert client.post(f'/api/projects/{pid}/runs', json={'recipe': 'shell', 'entry': 'anything'}).status_code == 422
    assert client.post(f'/api/projects/{pid}/runs', json={'test_size': 0.9}).status_code == 422
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../escape.py', 'print(1)')
    assert client.post(f'/api/projects/{pid}/repositories/upload', files={'file': ('unsafe.zip', archive.getvalue())}).status_code == 422
    assert not (module.DATA.parent / 'escape.py').exists()
    assert client.post('/api/projects', headers={'Origin': 'https://untrusted.example'}, json={'name': 'bad'}).status_code == 403


def test_scan_pdf_and_repository_import(client):
    pid = create(client)
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    pdf.write(stream)
    response = client.post(f'/api/projects/{pid}/documents', files={'file': ('scan.pdf', stream.getvalue(), 'application/pdf')})
    assert response.status_code == 422 and 'OCR' in response.json()['detail']
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('example/train.py', 'print("example")')
        z.writestr('example/README.md', 'Run train.py')
    repo = client.post(f'/api/projects/{pid}/repositories/upload', files={'file': ('repo.zip', archive.getvalue())}).json()
    details = client.get(f'/api/projects/{pid}/repositories/{repo["id"]}/inspect').json()
    assert details['entries'] == ['train.py'] and details['readme'] == 'Run train.py'


def test_pdf_pages_keep_text_locations(client):
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    pid = create(client)
    pdf = PdfWriter()
    for text in ['Method: logistic regression.', 'Dataset: Iris; metric: Accuracy.']:
        page = pdf.add_blank_page(width=400, height=300)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 200 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = stream
    buffer = io.BytesIO()
    pdf.write(buffer)
    response = client.post(f'/api/projects/{pid}/documents', files={'file': ('paper.pdf', buffer.getvalue(), 'application/pdf')})
    assert response.status_code == 200
    doc = response.json()
    assert doc['pages'] == 2 and 'Dataset: Iris' in doc['spans'][1]['text']
    result = client.post(f'/api/projects/{pid}/evidence', json={'question': 'Dataset Iris Accuracy'}).json()
    assert result['evidence'][0]['page'] == 2


def test_unknown_model_citations_are_not_shown_as_evidence(client, monkeypatch):
    pid = create(client)
    client.post(f'/api/projects/{pid}/demo')
    monkeypatch.setattr(module, 'model_json', lambda *_: {'answer': 'unsupported answer', 'claims': [{'text': 'invented', 'citations': ['fake-source']} ]})
    response = client.post(f'/api/projects/{pid}/evidence', json={'question': 'Iris分类数据集'})
    assert response.status_code == 200
    assert response.json()['claims'] == []
    assert 'invented' not in response.text and 'unsupported answer' not in response.text


@pytest.mark.skipif(not module.docker_available(), reason='Docker不可用')
def test_repository_code_runs_in_container_and_failure_is_real(client):
    pid = create(client)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('repo/train.py', 'import os,json\nfrom pathlib import Path\np=Path(os.environ["RESEARCH_OUTPUT"])\n(p/"metrics.json").write_text(json.dumps({"actual":7}))\nprint("container experiment completed")\n')
        z.writestr('repo/fail.py', 'raise RuntimeError("intentional test failure")\n')
        z.writestr('repo/wait.py', 'import time\nprint("waiting",flush=True)\ntime.sleep(60)\n')
    repo = client.post(f'/api/projects/{pid}/repositories/upload', files={'file': ('repo.zip', archive.getvalue())}).json()
    for entry, expected in [('train.py', 'succeeded'), ('fail.py', 'failed')]:
        response = client.post(f'/api/projects/{pid}/runs', json={'name': entry, 'recipe': 'repository', 'repository_id': repo['id'], 'entry': entry})
        assert response.status_code == 200, response.text
        rid = response.json()['id']
        for _ in range(80):
            result = client.get(f'/api/projects/{pid}/runs/{rid}').json()
            if result['status'] not in {'queued', 'running'}:
                break
            time.sleep(.25)
        assert result['status'] == expected, result['log']
        if expected == 'succeeded':
            assert result['metrics'] == {'actual': 7}
        else:
            assert 'intentional test failure' in result['log'] and not result['metrics']
    response = client.post(f'/api/projects/{pid}/runs', json={'name': 'cancel', 'recipe': 'repository', 'repository_id': repo['id'], 'entry': 'wait.py'})
    rid = response.json()['id']
    assert client.post(f'/api/projects/{pid}/runs/{rid}/cancel').status_code == 200
    for _ in range(30):
        if rid not in module.PROCESSES:
            break
        time.sleep(.1)
    assert client.get(f'/api/projects/{pid}/runs/{rid}').json()['status'] == 'cancelled'
    assert rid not in module.PROCESSES
