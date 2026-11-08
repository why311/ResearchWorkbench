import io
import json
import time
import zipfile

from tests.test_documents import client, project as create


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
