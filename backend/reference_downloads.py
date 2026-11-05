"""Bounded reference-list discovery and legal full-text imports, with per-item retry."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import io
import json
import re
import time
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import app as core
from . import discovery, paper_watch
from .ingestion import ingest, document

router = APIRouter(prefix='/api')
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='reference-download')
S3 = 'https://pmc-oa-opendata.s3.amazonaws.com'
with core.db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS reference_downloads(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),status TEXT NOT NULL,items TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL)')
    conn.execute("UPDATE reference_downloads SET status='interrupted' WHERE status IN ('queued','running')")


def read(pid, jid):
    core.project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM reference_downloads WHERE project_id=? AND id=?', (pid, jid)).fetchone()
    if not row:
        raise HTTPException(404, '下载任务不存在')
    return {**dict(row), 'items': json.loads(row['items'])}


def save(jid, items):
    with core.db() as conn:
        conn.execute('UPDATE reference_downloads SET items=?,updated=? WHERE id=?', (json.dumps(items, ensure_ascii=False), core.now(), jid))


def normalized(text):
    return ''.join(re.findall(r'\w', text.lower()))


def s3_read(url, maximum=2*1024*1024, params=None):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'pmc-oa-opendata.s3.amazonaws.com' or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise HTTPException(422, '下载地址不属于PMC官方开放数据存储')
    started = time.monotonic()
    try:
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            with client.stream('GET', url, params=params) as response:
                response.raise_for_status()
                result = bytearray()
                for block in response.iter_bytes():
                    if time.monotonic()-started>45:
                        raise HTTPException(504, 'PMC下载超时，请稍后重试')
                    result.extend(block)
                    if len(result) > maximum:
                        raise HTTPException(413, 'PMC返回内容超过大小限制')
                return bytes(result)
    except httpx.HTTPError:
        raise HTTPException(502, 'PMC开放数据暂时不可用，请重试') from None


def pmc_candidates(query):
    params = {'db': 'pmc', 'term': '('+query+') AND open_access[filter] AND has_pdf[filter] NOT pmc embargo[filter]', 'retmode': 'json', 'retmax': 3}
    data = discovery.public_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi', params)
    ids = data.get('esearchresult', {}).get('idlist', [])
    if not isinstance(ids, list) or any(not re.fullmatch(r'\d+', str(i)) for i in ids):
        raise HTTPException(502, 'PMC返回无效标识')
    if not ids:
        return []
    data = discovery.public_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi', {'db': 'pmc', 'id': ','.join(ids), 'retmode': 'json'})
    return [{'key': 'pmc:PMC'+i, 'title': data['result'][i]['title'], 'pmcid': 'PMC'+i,
             'url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC'+i+'/'} for i in ids if isinstance(data.get('result', {}).get(i), dict)]


def resolve(query):
    pmc = re.fullmatch(r'(?:https://pmc\.ncbi\.nlm\.nih\.gov/articles/)?(PMC\d+)/?', query.strip(), re.I)
    if pmc:
        key = pmc[1].upper()
        data = discovery.public_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi', {'db':'pmc','id':key[3:],'retmode':'json'})
        row = data.get('result', {}).get(key[3:], {})
        if not row.get('title'):
            raise HTTPException(404, '未找到此PMC题录')
        return [{'key':'pmc:'+key,'pmcid':key,'title':row['title'],'exact':True,'url':'https://pmc.ncbi.nlm.nih.gov/articles/'+key+'/'}], []
    identifier = re.sub(r'^(?:arxiv:|https://arxiv\.org/(?:abs|pdf)/)', '', query.strip(), flags=re.I).removesuffix('.pdf')
    if paper_watch.ARXIV.fullmatch(identifier):
        rows = paper_watch.parse_feed(paper_watch.download('https://export.arxiv.org/api/query', 2*1024*1024, params={'id_list': identifier, 'max_results': 1}))
        return [{**r, 'key': 'arxiv:'+r['arxiv_id'], 'exact': True} for r in rows], []
    target, errors = query, []
    doi = re.search(r'10\.\d{4,9}/[^\s<>"\]]+', query)
    if doi:
        from urllib.parse import quote
        row = discovery.public_json('https://api.crossref.org/works/'+quote(doi[0].rstrip('.,;'),safe='')).get('message', {})
        target = (row.get('title') or [query])[0]
    candidates = []
    try:
        clean = re.sub(r'[^\w\s-]', ' ', target).strip()
        rows = paper_watch.parse_feed(paper_watch.download('https://export.arxiv.org/api/query', 2*1024*1024, params={'search_query': 'ti:"'+clean+'"', 'max_results': 3}))
        candidates += [{**r, 'key': 'arxiv:'+r['arxiv_id']} for r in rows[:3]]
    except HTTPException as exc:
        errors.append(exc.detail)
    try:
        candidates += pmc_candidates(target)
    except HTTPException as exc:
        errors.append(exc.detail)
    for item in candidates:
        item['exact'] = normalized(item['title']) == normalized(target)
    return candidates, errors


def pmc_pdf(pmcid):
    if not re.fullmatch(r'PMC\d+', pmcid):
        raise HTTPException(422, 'PMC编号无效')
    listing = s3_read(S3+'/', params={'list-type': '2', 'prefix': pmcid+'.', 'delimiter': '/', 'max-keys': 100})
    if b'<!DOCTYPE' in listing.upper() or b'<!ENTITY' in listing.upper():
        raise HTTPException(502, 'PMC返回不支持的XML声明')
    try:
        tree = ET.fromstring(listing)
    except ET.ParseError:
        raise HTTPException(502, 'PMC未返回有效版本列表') from None
    prefixes = [e.text for e in tree.iter() if e.tag.endswith('}Prefix') and e.text and re.fullmatch(re.escape(pmcid)+r'\.\d+/', e.text)]
    # Version order is not a quality or recency judgment; retain the source version.
    for prefix in sorted(set(prefixes), key=lambda s: int(s.split('.')[1].rstrip('/')))[:10]:
        metadata = json.loads(s3_read(S3+'/'+prefix+prefix.rstrip('/')+'.json'))
        url = metadata.get('pdf_url', '')
        if metadata.get('is_pmc_openaccess') not in ('yes', True) or not metadata.get('license_code') or not isinstance(url, str):
            continue
        if url.startswith('s3://pmc-oa-opendata/'):
            url = S3+'/'+url.removeprefix('s3://pmc-oa-opendata/')
        parsed = urlparse(url)
        if parsed.path.startswith('/'+prefix) and parsed.path.endswith('.pdf'):
            return s3_read(url, 32*1024*1024), {'pmcid': pmcid, 'version': metadata.get('version'), 'license': metadata['license_code'], 'url': url, 'source': 'NLM PMC Article Datasets'}
    raise HTTPException(404, '未找到许可明确且可下载的PMC开放PDF，请自行取得合法全文')


def import_candidate(pid, candidate):
    key = candidate['key']
    with core.db() as conn:
        rows = conn.execute('SELECT items FROM reference_downloads WHERE project_id=?', (pid,)).fetchall()
        for row in rows:
            for old in json.loads(row['items']):
                if old.get('source_key') == key and old.get('document_id') and conn.execute('SELECT 1 FROM documents WHERE id=? AND project_id=?', (old['document_id'], pid)).fetchone():
                    return old['document_id']
    if key.startswith('arxiv:') and paper_watch.ARXIV.fullmatch(candidate.get('arxiv_id', '')):
        content = paper_watch.download('https://arxiv.org/pdf/'+candidate['arxiv_id'], 32*1024*1024, timeout=45)
        source = {k: candidate[k] for k in ('title', 'arxiv_id', 'url')}
    elif key.startswith('pmc:'):
        content, source = pmc_pdf(candidate.get('pmcid', ''))
        source['title'] = candidate['title']
    else:
        raise HTTPException(422, '没有可用的官方全文来源')
    if not content.startswith(b'%PDF-'):
        raise HTTPException(422, '来源未返回PDF，未导入全文')
    added = asyncio.run(ingest(pid, UploadFile(filename=key.replace(':','_').replace('/','_')+'.pdf', file=io.BytesIO(content))))
    with core.db() as conn:
        profile = json.loads(conn.execute('SELECT profile FROM document_ingestions WHERE id=?', (added['id'],)).fetchone()[0])
        profile['metadata_source'] = source
        conn.execute('UPDATE document_ingestions SET profile=? WHERE id=?', (json.dumps(profile, ensure_ascii=False), added['id']))
        conn.execute('UPDATE documents SET title=? WHERE id=? AND project_id=?', (candidate['title'][:300], added['document_id'], pid))
    return added['document_id']


def run(pid, jid):
    with core.db() as conn:
        if not conn.execute("UPDATE reference_downloads SET status='running' WHERE id=? AND status='queued'", (jid,)).rowcount:
            return
    items = read(pid, jid)['items']
    for item in items:
        if read(pid, jid)['status'] != 'running':
            return
        if item['status'] != 'pending':
            continue
        item.update(status='searching', error='')
        save(jid, items)
        try:
            candidates = item.get('candidates', [])
            selected = next((c for c in candidates if c['key']==item.get('selected_key')), None)
            if not selected:
                candidates, warnings = resolve(item['query'])
                item.update(candidates=candidates, warnings=warnings)
                exact = [c for c in candidates if c.get('exact')]
                selected = exact[0] if len(exact)==1 else None
            if selected:
                if read(pid, jid)['status'] != 'running':
                    item['status'] = 'pending'
                    save(jid, items)
                    return
                item['document_id'] = import_candidate(pid, selected)
                item.update(status='imported', source_key=selected['key'])
            else:
                item['status'] = 'needs_selection' if candidates else 'not_found'
        except (HTTPException, ValueError, KeyError, TypeError) as exc:
            item.update(status='failed', error=str(exc.detail) if isinstance(exc, HTTPException) else '题录或下载响应无效，请重试')
        save(jid, items)
    with core.db() as conn:
        conn.execute("UPDATE reference_downloads SET status='completed',updated=? WHERE id=? AND status='running'", (core.now(), jid))


class BatchBody(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=20)


@router.post('/projects/{pid}/reference-downloads')
def start(pid: str, body: BatchBody):
    core.project(pid)
    values = list(dict.fromkeys(q.strip() for q in body.queries))
    if any(not 2 <= len(q) <= 1500 for q in values):
        raise HTTPException(422, '每条题名或引用需为2—1500字符')
    jid = core.uid()
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT COUNT(*) FROM reference_downloads WHERE status IN ('queued','running')").fetchone()[0] >= 3:
            raise HTTPException(429, '已有3个下载任务，请稍后再试')
        if conn.execute('SELECT COUNT(*) FROM reference_downloads WHERE project_id=?', (pid,)).fetchone()[0] >= 30:
            raise HTTPException(422, '本项目已保存30个下载任务，请复用已有任务重试')
        conn.execute('INSERT INTO reference_downloads VALUES (?,?,?,?,?,?)', (jid, pid, 'queued', json.dumps([{'query':q,'status':'pending'} for q in values],ensure_ascii=False), core.now(),core.now()))
    POOL.submit(copy_context().run, run, pid, jid)
    return read(pid, jid)


@router.get('/projects/{pid}/reference-downloads')
def list_batches(pid: str):
    core.project(pid)
    with core.db() as conn:
        rows = conn.execute('SELECT id FROM reference_downloads WHERE project_id=? ORDER BY created DESC', (pid,)).fetchall()
    return [read(pid, r['id']) for r in rows]


class RetryBody(BaseModel):
    index: int = Field(ge=0, le=19)
    candidate_key: str = Field(default='', max_length=150)


@router.post('/projects/{pid}/reference-downloads/{jid}/retry')
def retry(pid: str, jid: str, body: RetryBody):
    record = read(pid, jid)
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT status FROM reference_downloads WHERE id=?', (jid,)).fetchone()[0]
        if current in {'queued', 'running'}:
            raise HTTPException(409, '请等待当前任务结束或停止后重试')
        items = record['items']
        if body.index >= len(items) or items[body.index]['status']=='imported':
            raise HTTPException(422, '该条不存在或已经导入')
        item = items[body.index]
        if body.candidate_key and not any(c['key']==body.candidate_key for c in item.get('candidates', [])):
            raise HTTPException(422, '所选题录不属于此条引用')
        item.update(status='pending', selected_key=body.candidate_key)
        conn.execute("UPDATE reference_downloads SET status='queued',items=?,updated=? WHERE id=?", (json.dumps(items,ensure_ascii=False),core.now(),jid))
    POOL.submit(copy_context().run, run, pid, jid)
    return read(pid, jid)


@router.post('/projects/{pid}/reference-downloads/{jid}/cancel')
def cancel(pid: str, jid: str):
    read(pid, jid)
    with core.db() as conn:
        conn.execute("UPDATE reference_downloads SET status='cancelled',updated=? WHERE id=? AND status IN ('queued','running')", (core.now(),jid))
    return read(pid, jid)
