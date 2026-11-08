import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

import pytest
from openpyxl import Workbook

from backend import app as core
from backend.analysis_runner import analyze
from tests.test_documents import client, project as create


def upload(client, pid, text):
    response = client.post(f'/api/projects/{pid}/datasets', files={'file': ('measures.csv', text.encode(), 'text/csv')})
    assert response.status_code == 200, response.text
    return response.json()


def execute(client, pid, did, plan, name='实际分析'):
    response = client.post(f'/api/projects/{pid}/analysis', json={'name': name, 'dataset_id': did, 'plan': plan})
    assert response.status_code == 200, response.text
    rid = response.json()['id']
    for _ in range(100):
        result = client.get(f'/api/projects/{pid}/analysis/{rid}').json()
        if result['run']['status'] not in {'running', 'queued'}:
            break
        time.sleep(.1)
    assert result['run']['status'] == 'succeeded', result['run']['log']
    return result


def test_analysis_numbers_and_exported_replay(client, tmp_path):
    pid = create(client)
    d = upload(client, pid, 'group,x,y\nA,1,2\nA,3,6\nB,5,10\nB,,14\nB,5,10\n')
    assert d['profile']['duplicates'] == 1
    assert d['profile']['fields'][1]['missing'] == 1
    plan = {'columns': ['x', 'y'], 'missing': 'median', 'deduplicate': True,
            'scales': {'y': .5}, 'methods': ['summary', 'groups', 'correlation'], 'group_by': 'group'}
    result = execute(client, pid, d['id'], plan)
    report = result['result']
    assert report['audit']['input_rows'] == 5
    assert report['audit']['duplicates_removed'] == 1
    assert report['audit']['imputed_cells'] == 1
    assert report['audit']['output_rows'] == 4
    assert report['summary'][0]['mean'] == 3
    assert report['summary'][1]['mean'] == 4
    assert report['summary'][0]['std'] == pytest.approx((8 / 3) ** .5)
    assert report['correlations'][0]['pearson_r'] == pytest.approx(8 / (160 ** .5))
    assert next(r for r in report['groups'] if r['group'] == 'B' and r['column'] == 'x')['mean'] == 4
    rid = result['run']['id']
    imported = client.post(f'/api/projects/{pid}/datasets/from-run', json={'run_id': rid, 'filename': 'cleaned.csv'})
    assert imported.status_code == 200, imported.text
    assert imported.json()['row_count'] == 4
    assert imported.json()['profile']['source_run_id'] == rid
    other = create(client)
    assert client.post(f'/api/projects/{other}/datasets/from-run', json={'run_id': rid, 'filename': 'cleaned.csv'}).status_code == 404
    exported = client.get(f'/api/projects/{pid}/analysis/{rid}/export')
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    assert {'analysis_runner.py', 'input.csv', 'config.json', 'environment.json', 'analysis.md'}.issubset(archive.namelist())
    for name in archive.namelist():
        (tmp_path / name).write_bytes(archive.read(name))
    process = subprocess.run([sys.executable, str(tmp_path / 'analysis_runner.py'), '--input', str(tmp_path / 'input.csv'), '--plan', str(tmp_path / 'config.json'), '--output', str(tmp_path / 'replay')], capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr
    replay = json.loads((tmp_path / 'replay' / 'analysis.json').read_text(encoding='utf-8'))
    assert replay == report


def test_filter_counts_constant_correlation_and_csv_safety(tmp_path):
    source = tmp_path / 'input.csv'
    source.write_text('name,x,y\n=SUM(A1),1,2\nnormal,1,\nother,1,4\ninvalid,no,6\n', encoding='utf-8')
    result = analyze(source, {'columns': ['x', 'y'], 'missing': 'keep', 'methods': ['correlation'], 'group_by': ''}, tmp_path / 'output')
    assert result['audit']['invalid_cells'] == 1
    assert result['correlations'][0]['n'] == 2 and result['correlations'][0]['pearson_r'] is None
    assert result['summary'][0]['std'] == 0
    assert next(csv.reader((tmp_path / 'output' / 'cleaned.csv').open(encoding='utf-8-sig')))[0] == 'name'
    rows = list(csv.reader((tmp_path / 'output' / 'cleaned.csv').open(encoding='utf-8-sig')))
    assert rows[1][0].startswith("'=")
    filtered = analyze(source, {'columns': ['x', 'y'], 'missing': 'drop', 'methods': ['summary'], 'scales': {'y': 2}, 'filters': [{'column': 'y', 'minimum': 5, 'maximum': 10}]}, tmp_path / 'filtered')
    assert filtered['audit']['filtered_rows'] == 3 and filtered['audit']['output_rows'] == 1
    assert filtered['summary'][1]['mean'] == 8


def test_excel_tsv_and_invalid_inputs(client):
    pid = create(client)
    workbook = Workbook()
    workbook.active.append(['group', 'score'])
    workbook.active.append(['A', 4])
    output = io.BytesIO()
    workbook.save(output)
    response = client.post(f'/api/projects/{pid}/datasets', files={'file': ('data.xlsx', output.getvalue())})
    assert response.status_code == 200 and response.json()['row_count'] == 1
    workbook.active['B2'] = '=1+3'
    output = io.BytesIO()
    workbook.save(output)
    assert client.post(f'/api/projects/{pid}/datasets', files={'file': ('formula.xlsx', output.getvalue())}).status_code == 422
    assert client.post(f'/api/projects/{pid}/datasets', files={'file': ('data.tsv', b'x\ty\n1\t2')}).status_code == 200
    assert client.post(f'/api/projects/{pid}/datasets', files={'file': ('bad.csv', b'x,x\n1,2')}).status_code == 422
    assert client.post(f'/api/projects/{pid}/datasets', files={'file': ('bad.csv', b'x,y\n1,2,3')}).status_code == 422
    d = upload(client, pid, 'x,y\n1,2\n3,4')
    other = create(client)
    assert client.post(f'/api/projects/{other}/analysis', json={'dataset_id': d['id'], 'plan': {'columns': ['x']}}).status_code == 404
    assert client.post(f'/api/projects/{pid}/analysis', json={'dataset_id': d['id'], 'plan': {'columns': ['x'], 'methods': ['correlation']}}).status_code == 422
    assert client.post(f'/api/projects/{pid}/analysis', json={'dataset_id': d['id'], 'plan': {'columns': ['x'], 'filters': [{'column': 'x', 'minimum': 10, 'maximum': 1}]}}).status_code == 422
