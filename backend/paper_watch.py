"""Opt-in arXiv watches, transparent recommendations and bounded PDF imports."""
import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
import re
import threading
import time
from typing import Literal
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer

from . import app as core

router = APIRouter(prefix='/api')
REQUEST_LOCK = threading.Lock()
IMPORT_LOCK = threading.Lock()
LAST_REQUEST = 0.0
ATOM = '{http://www.w3.org/2005/Atom}'
ARXIV = re.compile(r'^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v[1-9]\d*)?$')

with core.db() as conn:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS paper_watches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),query TEXT NOT NULL,enabled INTEGER NOT NULL,interval_hours INTEGER NOT NULL,last_checked TEXT,next_check TEXT NOT NULL,error TEXT NOT NULL,created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS watched_papers(watch_id TEXT NOT NULL REFERENCES paper_watches(id) ON DELETE CASCADE,arxiv_id TEXT NOT NULL,metadata TEXT NOT NULL,rating INTEGER NOT NULL DEFAULT 0,document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,seen TEXT NOT NULL,PRIMARY KEY(watch_id,arxiv_id));
    ''')


def watch(pid, wid):
    core.project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM paper_watches WHERE id=? AND project_id=?', (wid, pid)).fetchone()
    if not row:
        raise HTTPException(404, '文献追踪不存在')
    return dict(row)


def download(url, maximum, timeout=30, params=None):
    """No caller-supplied host, credentials or redirect to another service."""
    global LAST_REQUEST
    deadline = time.monotonic() + timeout
    with REQUEST_LOCK:
        delay = 3 - (time.monotonic() - LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
        LAST_REQUEST = time.monotonic()
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False,
                              headers={'User-Agent': 'ResearchWorkbench/0.1 (local academic reading tool)'}) as client:
                for _ in range(4):
                    parsed = urlparse(url)
                    if parsed.scheme != 'https' or parsed.hostname not in {'arxiv.org', 'export.arxiv.org'} or parsed.port not in (None, 443) or parsed.username or parsed.password:
                        raise HTTPException(422, '仅从arXiv官方HTTPS地址读取文献')
                    with client.stream('GET', url, params=params) as response:
                        if response.is_redirect:
                            url = urljoin(str(response.url), response.headers.get('location', ''))
                            params = None
                            continue
                        response.raise_for_status()
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            if time.monotonic() > deadline:
                                raise HTTPException(504, 'arXiv读取超时，请稍后重试')
                            content.extend(chunk)
                            if len(content) > maximum:
                                raise HTTPException(413, 'arXiv返回内容超过大小限制')
                        return bytes(content)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, 'arXiv暂时无法访问或限制请求，请稍后重试；已有题录保留') from exc
    raise HTTPException(502, 'arXiv重定向次数过多，未继续下载')


def parse_feed(content):
    if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise HTTPException(502, 'arXiv响应包含不支持的XML声明')
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise HTTPException(502, 'arXiv未返回有效题录，已有结果保留') from exc
    if root.tag != ATOM + 'feed':
        raise HTTPException(502, 'arXiv未返回Atom题录')
    result = []
    for entry in root.findall(ATOM + 'entry')[:30]:
        raw_id = entry.findtext(ATOM + 'id', '')
        identifier = raw_id.split('/abs/')[-1]
        if not ARXIV.fullmatch(identifier):
            if 'errors' in raw_id:
                raise HTTPException(422, 'arXiv未接受此检索式，请检查关键词或字段语法')
            continue
        title = ' '.join(entry.findtext(ATOM + 'title', '').split())[:1000]
        abstract = ' '.join(entry.findtext(ATOM + 'summary', '').split())[:16000]
        comment = entry.findtext('{http://arxiv.org/schemas/atom}comment', '')
        repositories = sorted(set(re.findall(r'https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', abstract + ' ' + comment)))
        result.append({'arxiv_id': identifier, 'title': title, 'abstract': abstract,
                       'authors': [a.findtext(ATOM + 'name', '') for a in entry.findall(ATOM + 'author')][:100],
                       'published': entry.findtext(ATOM + 'published', ''), 'updated': entry.findtext(ATOM + 'updated', ''),
                       'categories': [c.get('term', '') for c in entry.findall(ATOM + 'category')],
                       'repositories': repositories, 'url': 'https://arxiv.org/abs/' + identifier})
    return result


def query_params(query):
    identifier = re.sub(r'^(?:https://arxiv\.org/(?:abs|pdf)/|arxiv:)', '', query.strip(), flags=re.I)
    if ARXIV.fullmatch(identifier):
        # An unversioned identifier asks arXiv for its current revision.
        return {'id_list': identifier, 'max_results': 1}
    return {'search_query': query, 'start': 0, 'max_results': 30,
            'sortBy': 'lastUpdatedDate', 'sortOrder': 'descending'}


class WatchBody(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    enabled: bool = False
    interval_hours: int = Field(default=24, ge=6, le=168)


@router.post('/projects/{pid}/paper-watches')
def add_watch(pid: str, body: WatchBody):
    core.project(pid)
    if len(body.query.strip()) < 2:
        raise HTTPException(422, '请填写至少两个字符的关键词或arXiv检索式')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT COUNT(*) FROM paper_watches WHERE project_id=?', (pid,)).fetchone()[0] >= 10:
            raise HTTPException(422, '每个项目最多10个追踪，请先整理现有追踪')
        wid = core.uid()
        conn.execute('INSERT INTO paper_watches VALUES (?,?,?,?,?,?,?,?,?)',
                     (wid, pid, body.query.strip(), int(body.enabled), body.interval_hours, None, core.now(), '', core.now()))
    return watch(pid, wid)


@router.put('/projects/{pid}/paper-watches/{wid}')
def update_watch(pid: str, wid: str, body: WatchBody):
    existing = watch(pid, wid)
    if body.query.strip() != existing['query']:
        raise HTTPException(422, '改变检索词请新建追踪，避免混合不同检索历史')
    with core.db() as conn:
        conn.execute('UPDATE paper_watches SET enabled=?,interval_hours=?,next_check=? WHERE id=?',
                     (int(body.enabled), body.interval_hours, core.now(), wid))
    return watch(pid, wid)


@router.delete('/projects/{pid}/paper-watches/{wid}')
def delete_watch(pid: str, wid: str):
    watch(pid, wid)
    with core.db() as conn:
        conn.execute('DELETE FROM paper_watches WHERE id=?', (wid,))
    return {'deleted': True}


@router.post('/projects/{pid}/paper-watches/{wid}/refresh')
def refresh_watch(pid: str, wid: str):
    record = watch(pid, wid)
    # Avoid repeated clicks hammering a public API; the API limit also covers different watches.
    if record['last_checked'] and (datetime.now(timezone.utc) - datetime.fromisoformat(record['last_checked'])).total_seconds() < 60:
        raise HTTPException(429, '刚刚已刷新，请一分钟后再试')
    try:
        rows = parse_feed(download('https://export.arxiv.org/api/query', 2 * 1024 * 1024,
                                  params=query_params(record['query'])))
    except HTTPException as exc:
        with core.db() as conn:
            conn.execute('UPDATE paper_watches SET error=?,next_check=? WHERE id=?',
                         (str(exc.detail), (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), wid))
        raise
    checked = core.now()
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if not conn.execute('SELECT 1 FROM paper_watches WHERE id=?', (wid,)).fetchone():
            raise HTTPException(404, '此追踪已删除')
        for row in rows:
            base_id = re.sub(r'v\d+$', '', row['arxiv_id'])
            conn.execute('INSERT INTO watched_papers VALUES (?,?,?,0,NULL,?) ON CONFLICT(watch_id,arxiv_id) DO UPDATE SET metadata=excluded.metadata,seen=excluded.seen',
                         (wid, base_id, json.dumps(row, ensure_ascii=False), checked))
        # Retain a bounded recent pool, keeping feedback and imported papers.
        conn.execute('DELETE FROM watched_papers WHERE watch_id=? AND rating=0 AND document_id IS NULL AND arxiv_id NOT IN (SELECT arxiv_id FROM watched_papers WHERE watch_id=? ORDER BY seen DESC,arxiv_id LIMIT 200)', (wid, wid))
        conn.execute('UPDATE paper_watches SET last_checked=?,next_check=?,error=? WHERE id=?',
                     (checked, (datetime.now(timezone.utc) + timedelta(hours=record['interval_hours'])).isoformat(), '', wid))
    return {'count': len(rows), 'watch': watch(pid, wid)}


@router.get('/projects/{pid}/paper-watches')
def list_watches(pid: str):
    core.project(pid)
    with core.db() as conn:
        watches = [dict(r) for r in conn.execute('SELECT * FROM paper_watches WHERE project_id=? ORDER BY created,id', (pid,))]
        papers = [dict(r) for r in conn.execute('SELECT p.* FROM watched_papers p JOIN paper_watches w ON w.id=p.watch_id WHERE w.project_id=? ORDER BY p.seen DESC,p.arxiv_id LIMIT 1000', (pid,))]
        docs = [dict(r) for r in conn.execute('SELECT id,title FROM documents WHERE project_id=? ORDER BY created DESC LIMIT 100', (pid,))]
    items = [{**json.loads(r['metadata']), 'watch_id': r['watch_id'], 'key': r['arxiv_id'],
              'rating': r['rating'], 'document_id': r['document_id'], 'seen': r['seen']} for r in papers]
    # Explainable title/abstract TF-IDF; never label a text similarity as scientific relevance.
    interests = ' '.join(d['title'] for d in docs) + ' ' + core.project(pid)['question']
    liked = [p['title'] + ' ' + p['abstract'] for p in items if p['rating'] == 1]
    query = interests + ' ' + ' '.join(liked[:20])
    scores = [0.0] * len(items)
    if query.strip() and items:
        try:
            vectors = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), max_features=20000).fit_transform([query] + [p['title'] + ' ' + p['abstract'] for p in items])
            scores = (vectors[1:] @ vectors[0].T).toarray().ravel().tolist()
        except ValueError:
            pass
    for item, score in zip(items, scores):
        item['similarity'] = round(score, 4)
        item['reasons'] = [('与项目题名、问题及已点赞摘要的词项相似度 ' + f'{score:.3f}') if query.strip() else '尚无本地兴趣资料；按arXiv更新时间查看']
        if item['repositories']:
            item['reasons'].append('摘要或作者备注含GitHub链接；仓库可用性与复现效果尚未核实')
    items.sort(key=lambda p: (p['rating'] != -1, p['similarity'], p['updated']), reverse=True)
    return {'watches': watches, 'items': items, 'scope': '仅检索条件下最近更新的30条，非穷尽监控；题录和摘要不会作为项目全文证据。自动刷新仅在本机服务运行时执行，失败保留已有结果。'}


def paper(pid, wid, key):
    watch(pid, wid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM watched_papers WHERE watch_id=? AND arxiv_id=?', (wid, key)).fetchone()
    if not row:
        raise HTTPException(404, '未找到此追踪中的论文')
    return dict(row)


class RatingBody(BaseModel):
    arxiv_id: str
    rating: Literal[-1, 0, 1]


@router.put('/projects/{pid}/paper-watches/{wid}/feedback')
def rate(pid: str, wid: str, body: RatingBody):
    paper(pid, wid, body.arxiv_id)
    with core.db() as conn:
        conn.execute('UPDATE watched_papers SET rating=? WHERE watch_id=? AND arxiv_id=?', (body.rating, wid, body.arxiv_id))
    return {'saved': True}


class ImportBody(BaseModel):
    arxiv_id: str


@router.post('/projects/{pid}/paper-watches/{wid}/import')
def import_paper(pid: str, wid: str, body: ImportBody):
    from .ingestion import ingest, job
    with IMPORT_LOCK:
        row = paper(pid, wid, body.arxiv_id)
        with core.db() as conn:
            existing = conn.execute('SELECT p.document_id FROM watched_papers p JOIN paper_watches w ON p.watch_id=w.id WHERE w.project_id=? AND p.arxiv_id=? AND p.document_id IS NOT NULL LIMIT 1', (pid, body.arxiv_id)).fetchone()
            prior = conn.execute('SELECT id FROM document_ingestions WHERE document_id=?', (existing['document_id'],)).fetchone() if existing else None
        if existing:
            return {'document_id': existing['document_id'], 'existing': True, 'ingestion': job(pid, prior['id']) if prior else None}
        metadata = json.loads(row['metadata'])
        identifier = metadata['arxiv_id']
        if not ARXIV.fullmatch(identifier):
            raise HTTPException(422, '论文标识无效，未发出下载请求')
        content = download('https://arxiv.org/pdf/' + identifier, 20 * 1024 * 1024, timeout=45)
        if not content.startswith(b'%PDF-'):
            raise HTTPException(422, 'arXiv没有返回PDF，未加入全文库')
        # Use the existing page/resource limits, OCR queue, original-file preservation and ownership checks.
        added = asyncio.run(ingest(pid, UploadFile(filename=identifier.replace('/', '_') + '.pdf', file=io.BytesIO(content))))
        with core.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE watched_papers SET document_id=? WHERE watch_id=? AND arxiv_id=?', (added['document_id'], wid, body.arxiv_id))
            conn.execute('UPDATE documents SET title=? WHERE id=? AND project_id=?', (metadata['title'], added['document_id'], pid))
            saved = conn.execute('SELECT profile FROM document_ingestions WHERE id=?', (added['id'],)).fetchone()
            profile = json.loads(saved['profile'])
            if profile.get('title'):
                profile['parsed_title'] = profile['title']
            profile['title'] = metadata['title'][:300]
            profile['metadata_source'] = {k: metadata[k] for k in ('title', 'authors', 'published', 'updated', 'arxiv_id', 'url')}
            conn.execute('UPDATE document_ingestions SET profile=? WHERE id=?', (json.dumps(profile, ensure_ascii=False), added['id']))
        return {'document_id': added['document_id'], 'existing': False, 'ingestion': added}


def run_due(stop):
    while not stop.wait(30):
        with core.db() as conn:
            due = [dict(r) for r in conn.execute('SELECT id,project_id FROM paper_watches WHERE enabled=1 AND next_check<=? ORDER BY next_check LIMIT 10', (core.now(),))]
        for row in due:
            if stop.is_set():
                return
            try:
                refresh_watch(row['project_id'], row['id'])
            except HTTPException:
                pass  # A failed fetch records its error and next retry on the watch.


def start_scheduler():
    stop = threading.Event()
    worker = threading.Thread(target=run_due, args=(stop,), daemon=True, name='arxiv-watch')
    worker.start()
    return stop
