import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import HTTPException

from backend import app as core, ingestion as documents, paper_watch as watches
from tests.test_documents import client, project as create
from tests.test_documents import pdf as pdf_bytes


FEED = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><id>http://arxiv.org/abs/2601.12345v2</id><title>Seed reproducibility study</title><summary>Random seeds and reproducibility. Code: https://github.com/example/repro</summary><published>2026-01-01T00:00:00Z</published><updated>2026-02-01T00:00:00Z</updated><author><name>Fixture Author</name></author><category term="cs.LG"/></entry>
<entry><id>http://arxiv.org/abs/hep-th/9901001v3</id><title>Unrelated physical theory</title><summary>Quantum field theory.</summary><updated>2026-01-01T00:00:00Z</updated></entry></feed>'''


def add(client, pid, query='all:reproducibility'):
    response = client.post(f'/api/projects/{pid}/paper-watches', json={'query': query})
    assert response.status_code == 200
    return response.json()['id']


def reset_checked(wid):
    with core.db() as conn:
        conn.execute('UPDATE paper_watches SET last_checked=NULL WHERE id=?', (wid,))


def test_watch_refresh_feedback_versions_and_project_isolation(client, monkeypatch):
    pid, other = create(client), create(client)
    wid = add(client, pid)
    base = f'/api/projects/{pid}/paper-watches'
    monkeypatch.setattr(watches, 'download', lambda *_args, **_kwargs: FEED)
    assert client.post(base + f'/{wid}/refresh').json()['count'] == 2
    data = client.get(base).json()
    assert data['watches'][0]['enabled'] == 0
    paper = next(p for p in data['items'] if p['key'] == '2601.12345')
    assert paper['authors'] == ['Fixture Author'] and paper['repositories'] == ['https://github.com/example/repro']
    assert paper['document_id'] is None
    assert client.post(base + f'/{wid}/refresh').status_code == 429
    feedback = {'arxiv_id': '2601.12345', 'rating': 1}
    assert client.put(base + f'/{wid}/feedback', json=feedback).status_code == 200
    reset_checked(wid)
    monkeypatch.setattr(watches, 'download', lambda *_args, **_kwargs: FEED.replace(b'12345v2', b'12345v7'))
    assert client.post(base + f'/{wid}/refresh').status_code == 200
    items = client.get(base).json()['items']
    assert len(items) == 2 and next(p for p in items if p['key'] == '2601.12345')['rating'] == 1
    assert next(p for p in items if p['key'] == '2601.12345')['arxiv_id'].endswith('v7')
    foreign = f'/api/projects/{other}/paper-watches/{wid}'
    assert client.post(foreign + '/refresh').status_code == 404
    assert client.put(foreign + '/feedback', json=feedback).status_code == 404
    assert client.post(foreign + '/import', json={'arxiv_id': '2601.12345'}).status_code == 404
    assert client.delete(foreign).status_code == 404
    assert client.get(f'/api/projects/{other}/paper-watches').json()['items'] == []
    assert client.delete(base + '/' + wid).status_code == 200
    with core.db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM watched_papers').fetchone()[0] == 0


def test_failed_refresh_preserves_metadata_and_records_retry(client, monkeypatch):
    pid = create(client)
    wid = add(client, pid)
    base = f'/api/projects/{pid}/paper-watches'
    monkeypatch.setattr(watches, 'download', lambda *_args, **_kwargs: FEED)
    client.post(base + f'/{wid}/refresh')
    reset_checked(wid)
    monkeypatch.setattr(watches, 'download', lambda *_args, **_kwargs: b'<html>not a feed</html>')
    assert client.post(base + f'/{wid}/refresh').status_code == 502
    data = client.get(base).json()
    assert len(data['items']) == 2 and data['watches'][0]['error']
    assert datetime.fromisoformat(data['watches'][0]['next_check']) > datetime.now(timezone.utc)
    assert client.post(base, json={'query': '  '}).status_code == 422
    assert client.post(base, json={'query': 'test', 'interval_hours': 1}).status_code == 422
    assert client.put(base + '/' + wid, json={'query': 'new query'}).status_code == 422
    with pytest.raises(HTTPException):
        watches.parse_feed(b'<!DOCTYPE feed [<!ENTITY x "bad">]><feed/>')
    assert watches.query_params('https://arxiv.org/abs/1706.03762') == {'id_list': '1706.03762', 'max_results': 1}
    assert watches.query_params('arXiv:hep-th/9901001v3')['id_list'] == 'hep-th/9901001v3'
    assert watches.query_params('ti:transformer')['sortBy'] == 'lastUpdatedDate'


def test_import_reuses_queue_ownership_and_same_paper_in_other_watch(client, monkeypatch):
    pid = create(client)
    wid, second = add(client, pid), add(client, pid, 'ti:seed')
    base = f'/api/projects/{pid}/paper-watches'
    calls = []
    def fetch(url, *_args, **_kwargs):
        calls.append(url)
        return FEED if '/api/query' in url else pdf_bytes()
    monkeypatch.setattr(watches, 'download', fetch)
    monkeypatch.setattr(documents.POOL, 'submit', lambda *_: None)
    client.post(base + f'/{wid}/refresh')
    client.post(base + f'/{second}/refresh')
    body = {'arxiv_id': '2601.12345'}
    result = client.post(base + f'/{wid}/import', json=body).json()
    assert result['ingestion']['status'] == 'queued' and not result['existing']
    assert calls[-1] == 'https://arxiv.org/pdf/2601.12345v2'
    did = result['document_id']
    assert (core.DATA / 'documents' / did / 'original.pdf').read_bytes().startswith(b'%PDF')
    assert client.post(base + f'/{second}/import', json=body).json()['document_id'] == did
    assert len([url for url in calls if '/pdf/' in url]) == 1
    assert client.post(base + f'/{wid}/import', json={'arxiv_id': 'https://localhost/secret'}).status_code == 404
    # The public stage has no document-delete route; verify the FK behavior directly.
    with core.db() as conn:
        conn.execute('DELETE FROM documents WHERE id=?',(did,))
    assert next(p for p in client.get(base).json()['items'] if p['watch_id'] == wid and p['key'] == body['arxiv_id'])['document_id'] is None


def test_download_rejects_external_redirect_and_size_limit(monkeypatch):
    real_client = httpx.Client
    requested = []
    def redirect(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://127.0.0.1:1234/private'})
    monkeypatch.setattr(watches.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(redirect), **kwargs))
    monkeypatch.setattr(watches, 'LAST_REQUEST', -100)
    with pytest.raises(HTTPException) as exc:
        watches.download('https://arxiv.org/pdf/1706.03762', 100)
    assert exc.value.status_code == 422 and len(requested) == 1
    monkeypatch.setattr(watches.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b'x' * 101)), **kwargs))
    monkeypatch.setattr(watches, 'LAST_REQUEST', -100)
    with pytest.raises(HTTPException) as exc:
        watches.download('https://export.arxiv.org/api/query', 100)
    assert exc.value.status_code == 413


def test_completed_pdf_keeps_arxiv_title_instead_of_parser_candidate(client, monkeypatch):
    pid = create(client)
    wid = add(client, pid)
    base = f'/api/projects/{pid}/paper-watches/{wid}'
    monkeypatch.setattr(watches, 'download', lambda url, *_args, **_kwargs: FEED if '/api/query' in url else pdf_bytes())
    assert client.post(base + '/refresh').status_code == 200
    imported = client.post(base + '/import', json={'arxiv_id': '2601.12345'}).json()
    jid = imported['ingestion']['id']
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        record = client.get(f'/api/projects/{pid}/document-ingestions/{jid}').json()
        if record['status'] not in {'queued', 'running'}:
            break
        time.sleep(.1)
    assert record['status'] == 'completed', record
    assert record['profile']['title'] == 'Seed reproducibility study'
    assert record['profile']['parsed_title'] != record['profile']['title']
    assert record['profile']['metadata_source']['arxiv_id'] == '2601.12345v2'
    assert record['profile']['arxiv'] == '2601.12345' and record['profile']['version'] == 2
    project = client.get(f'/api/projects/{pid}').json()
    assert project['documents'][0]['title'] == 'Seed reproducibility study'


def test_scheduler_refreshes_only_enabled_due_watches(client, monkeypatch):
    pid = create(client)
    first, second = add(client, pid), add(client, pid)
    with core.db() as conn:
        conn.execute('UPDATE paper_watches SET enabled=1,next_check=? WHERE id=?', ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), first))
    stop, calls = threading.Event(), []
    class OneCycle:
        def wait(self, _):
            return stop.is_set()
        def is_set(self):
            return stop.is_set()
    def refresh(project_id, watch_id):
        calls.append((project_id, watch_id))
        stop.set()
    monkeypatch.setattr(watches, 'refresh_watch', refresh)
    watches.run_due(OneCycle())
    assert calls == [(pid, first)] and second != first
