import io
import json
import subprocess
import sys
import zipfile

import pytest

from backend import app as core
from tests.test_documents import client, project as create
from tests.test_research_experiments import wait_series


TRAIN = '''import argparse,json,os,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--seed',type=int);p.add_argument('--weight',type=float);p.add_argument('--pause',type=float,default=0)
a=p.parse_args();time.sleep(a.pause)
try:
 Path('/workspace/should-not-write.txt').write_text('bad')
 raise RuntimeError('Repository was writable')
except OSError:
 print('repository remains read-only',flush=True)
out=Path(os.environ['RESEARCH_OUTPUT']);(out/'metrics.json').write_text(json.dumps({'score':a.weight+a.seed/1000}))
(out/'config.json').write_text('{}')
(out/'link.txt').symlink_to('/workspace/train.py')
(out/'report.html').write_text('<script>void 0</script>')
print('actual experiment completed',a.seed,a.weight,flush=True)
'''


def repository(client, pid):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('repo/train.py', TRAIN)
    return client.post(f'/api/projects/{pid}/repositories/upload', files={'file': ('series-fixture.zip', data.getvalue())}).json()


def body(repo):
    return {'name': '外部仓库真实参数对照', 'factor': 'argument', 'seeds': [11, 12], 'values': [3], 'control_value': 1,
        'parameter': '--weight', 'seed_parameter': '--seed', 'metric': 'score', 'base': {'recipe': 'repository', 'repository_id': repo['id'], 'entry': 'train.py', 'timeout': 30}}


@pytest.mark.skipif(not core.docker_available(), reason='Docker不可用')
def test_real_repository_series_and_isolated_replay(client, tmp_path):
    pid = create(client)
    repo = repository(client, pid)
    response = client.post(f'/api/projects/{pid}/experiment-series', json=body(repo))
    assert response.status_code == 200, response.text
    result = wait_series(client, pid, response.json()['id'])
    assert result['status'] == 'succeeded' and result['completed'] == 4
    assert len(result['paired']) == 2 and all(abs(r['delta'] - 2) < 1e-9 for r in result['paired'])
    assert all('repository remains read-only' in r['log'] and '--network none' in r['log'] for r in result['runs'])
    assert all(r['config']['args'] == ['--seed', str(r['config']['seed']), '--weight', str(1 if r['config']['variant_index'] == 0 else 3)] for r in result['runs'])
    run_id = result['runs'][0]['id']
    paths = f'/api/projects/{pid}/runs/{run_id}/artifacts/'
    assert client.get(paths + 'link.txt').status_code == 404
    assert client.get(paths + 'config.json').json()['entry'] == 'train.py'
    assert client.get(paths + 'report.html').headers['content-disposition'].startswith('attachment;')
    response = client.get(f'/api/projects/{pid}/experiment-series/{result["id"]}/export')
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {'repository/train.py', 'replay_repository.py', 'Dockerfile.runner'} <= set(archive.namelist())
    archive.extractall(tmp_path / 'export')
    folder = tmp_path / 'export'; rid = result['runs'][0]['id']
    replay = subprocess.run([sys.executable, str(folder / 'replay_repository.py'), '--config', str(folder / 'runs' / rid / 'config.json'), '--repository', str(folder / 'repository'), '--output', str(folder / 'replay')], capture_output=True, timeout=45)
    assert replay.returncode == 0, replay.stderr
    assert json.loads((folder / 'replay' / 'metrics.json').read_text()) == result['runs'][0]['metrics']


def test_repository_series_validation_keeps_project_and_argument_boundaries(client, monkeypatch):
    monkeypatch.setattr(core, 'docker_available', lambda: False)
    pid, other = create(client), create(client)
    repo = repository(client, pid)
    value = body(repo)
    # Fail before a new queue or process is created.
    for invalid in [{'seed_parameter': '--weight'}, {'values': []}, {'values': [1]}, {'parameter': '--bad;command'}, {'base': {**value['base'], 'args': ['--seed=123']}}]:
        assert client.post(f'/api/projects/{pid}/experiment-series', json={**value, **invalid}).status_code == 422
    assert client.post(f'/api/projects/{other}/experiment-series', json=value).status_code == 422
    with core.db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM experiment_series').fetchone()[0] == 0
