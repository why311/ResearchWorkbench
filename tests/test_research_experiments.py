import io
import json
import statistics
import subprocess
import sys
import threading
import time
import zipfile

import pytest

from backend import app as core, research as research_api
from tests.test_documents import client, project as create


def wait_series(client, pid, sid):
    for _ in range(200):
        data = client.get(f'/api/projects/{pid}/experiment-series/{sid}').json()
        if data['status'] not in {'queued', 'running'}:
            return data
        time.sleep(.1)
    pytest.fail('对照实验未在预期时间内完成')


def note(client, pid):
    doc = client.post(f'/api/projects/{pid}/documents', files={'file': ('paper.md', b'Research setup for Iris.')}).json()
    body = {'title': '标准化是否稳定改善结果', 'hypothesis': '不同特征量纲可能影响正则化。',
            'prediction': '观察同一划分下的accuracy差值，差值方向不一致时保留不确定性。',
            'source_refs': [{'document_id': doc['id'], 'span_id': 'p1-s1'}]}
    response = client.post(f'/api/projects/{pid}/research-notes', json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def test_paired_real_experiments_note_and_replay(client, tmp_path, monkeypatch):
    # Some system clocks return identical timestamps for a submitted batch.
    monkeypatch.setattr(core, 'now', lambda: '2026-10-13T12:00:00+00:00')
    pid = create(client)
    research, body = note(client, pid)
    response = client.post(f'/api/projects/{pid}/experiment-series', json={'name': '真实配对对照', 'seeds': [11, 12], 'note_id': research['id']})
    assert response.status_code == 200, response.text
    result = wait_series(client, pid, response.json()['id'])
    assert result['status'] == 'succeeded' and result['completed'] == 4
    assert [r['id'] for r in client.get(f'/api/projects/{pid}/experiment-workspace').json()['runs']] == result['run_ids'][::-1]
    assert len(result['paired']) == 2
    for pair in result['paired']:
        target = next(r for r in result['runs'] if r['id'] == pair['run_id'])
        control = next(r for r in result['runs'] if r['config']['variant_index'] == 0 and r['config']['seed'] == pair['seed'])
        assert target['config']['standardize'] is False and control['config']['standardize'] is True
        assert target['config']['regularization'] == control['config']['regularization']
        assert target['config']['test_size'] == control['config']['test_size']
        assert pair['delta'] == target['metrics']['accuracy'] - control['metrics']['accuracy']
    summary = result['summary'][1]
    assert summary['n'] == summary['paired_n'] == 2
    assert summary['paired_mean_delta'] == statistics.mean(p['delta'] for p in result['paired'])
    assert summary['positive_pairs'] + summary['negative_pairs'] + summary['ties'] == 2
    updated_note = client.get(f'/api/projects/{pid}/research-notes/{research["id"]}').json()
    assert updated_note['outcome'] == 'testing'  # Execution does not decide the hypothesis.
    assert len(updated_note['run_ids']) == 4 and updated_note['gaps'] == []
    body.update(run_ids=updated_note['run_ids'], outcome='inconclusive', decision='小数据集与重复划分仅用于流程验证，不能支持泛化结论。')
    assert client.put(f'/api/projects/{pid}/research-notes/{research["id"]}', json=body).status_code == 200
    rid = result['runs'][0]['id']
    exported = zipfile.ZipFile(io.BytesIO(client.get(f'/api/projects/{pid}/research-notes/{research["id"]}/export').content))
    sources = json.loads(exported.read('sources.json'))
    assert len(sources['runs']) == 4
    assert sources['sources'][0]['text'] and sources['outcome'] == 'inconclusive'
    assert '真实配对对照' in exported.read('research-note.md').decode()
    archive = zipfile.ZipFile(io.BytesIO(client.get(f'/api/projects/{pid}/experiment-series/{result["id"]}/export').content))
    for name in archive.namelist():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(name))
    rerun = subprocess.run([sys.executable, str(tmp_path / 'experiment.py'), '--config', str(tmp_path / 'runs' / rid / 'config.json'), '--output', str(tmp_path / 'replay')], capture_output=True, timeout=30)
    assert rerun.returncode == 0, rerun.stderr
    assert json.loads((tmp_path / 'replay' / 'metrics.json').read_text()) == result['runs'][0]['metrics']


def test_partial_series_uses_only_successful_pairs(client, monkeypatch):
    pid = create(client)
    real_execute = core.execute_run
    def execute(pid, rid, config):
        if config['seed'] == 11 and config['variant_index'] == 0:
            core.run_update(rid, status='failed', log='测试注入的执行故障', finished=core.now())
        else:
            real_execute(pid, rid, config)
    monkeypatch.setattr(core, 'execute_run', execute)
    started = client.post(f'/api/projects/{pid}/experiment-series', json={'seeds': [11, 12]}).json()
    result = wait_series(client, pid, started['id'])
    assert result['status'] == 'partial'
    assert result['summary'][0]['n'] == 1 and result['summary'][0]['std'] is None
    assert result['summary'][1]['n'] == 2 and result['summary'][1]['paired_n'] == 1
    assert [p['seed'] for p in result['paired']] == [12]
    assert result['paired'][0]['control'] != 0


def test_cancellation_never_launches_remaining_queue(client, monkeypatch):
    pid = create(client)
    existing, body = note(client, pid)
    body.update(outcome='unsupported', decision='原有作者判断；新运行不能自动覆盖它。')
    client.put(f'/api/projects/{pid}/research-notes/{existing["id"]}', json=body)
    entered, released, stopped, finished = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    launched = []
    def execute(pid, rid, config):
        launched.append(rid)
        core.run_update(rid, status='running')
        entered.set()
        released.wait(5)
        stopped.set()
    monkeypatch.setattr(core, 'execute_run', execute)
    original = research_api.execute_series
    def monitored(pid, sid):
        try:
            original(pid, sid)
        finally:
            finished.set()
    monkeypatch.setattr(research_api, 'execute_series', monitored)
    started = client.post(f'/api/projects/{pid}/experiment-series', json={'seeds': [11, 12], 'note_id': existing['id']}).json()
    assert entered.wait(3)
    assert client.get(f'/api/projects/{pid}/experiment-series/{started["id"]}/export').status_code == 409
    cancelled = client.post(f'/api/projects/{pid}/experiment-series/{started["id"]}/cancel').json()
    released.set()
    assert stopped.wait(3)
    assert finished.wait(3)
    assert cancelled['status'] == 'cancelled'
    assert all(r['status'] == 'cancelled' for r in cancelled['runs'])
    assert len(launched) == 1 and not cancelled['paired']
    assert all(s['mean'] is None for s in cancelled['summary'])
    assert client.get(f'/api/projects/{pid}/research-notes/{existing["id"]}').json()['outcome'] == 'unsupported'


def test_reference_boundaries_and_series_parameters(client):
    pid, other = create(client), create(client)
    research, body = note(client, pid)
    assert client.post(f'/api/projects/{other}/research-notes', json=body).status_code == 422
    assert client.get(f'/api/projects/{other}/research-notes/{research["id"]}').status_code == 404
    assert client.post(f'/api/projects/{other}/experiment-series', json={'note_id': research['id']}).status_code == 404
    assert client.post(f'/api/projects/{pid}/experiment-series', json={'seeds': [1, 1]}).status_code == 422
    assert client.post(f'/api/projects/{pid}/experiment-series', json={'factor': 'regularization', 'values': [1]}).status_code == 422
    assert client.post(f'/api/projects/{pid}/experiment-series', json={'factor': 'regularization', 'values': [0]}).status_code == 422
    assert client.post(f'/api/projects/{pid}/experiment-series', json={'base': {'recipe': 'repository'}}).status_code == 422
    body['source_refs'][0]['span_id'] = 'missing'
    assert client.put(f'/api/projects/{pid}/research-notes/{research["id"]}', json=body).status_code == 422
    with core.db() as db:
        assert db.execute('SELECT COUNT(*) FROM experiment_series').fetchone()[0] == 0
