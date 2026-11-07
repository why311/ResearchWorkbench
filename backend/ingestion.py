"""Structured ingestion, page storage and source-aware document access."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from pypdf import PdfReader

from . import app as core

router = APIRouter(prefix='/api')
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='document')
PROCESSES = {}
LOCK = threading.Lock()

with core.db() as conn:
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(documents)')}
    if 'matrix' not in columns: conn.execute("ALTER TABLE documents ADD COLUMN matrix TEXT NOT NULL DEFAULT '{}'")
    if 'created' not in columns: conn.execute("ALTER TABLE documents ADD COLUMN created TEXT NOT NULL DEFAULT ''")
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS document_ingestions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),document_id TEXT NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,status TEXT NOT NULL,completed INTEGER NOT NULL,total INTEGER NOT NULL,profile TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS document_pages(document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,page INTEGER NOT NULL,width REAL NOT NULL,height REAL NOT NULL,method TEXT NOT NULL,details TEXT NOT NULL,PRIMARY KEY(document_id,page));
    CREATE TABLE IF NOT EXISTS document_blocks(document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,span_id TEXT NOT NULL,page INTEGER NOT NULL,ordinal INTEGER NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,bbox TEXT NOT NULL,details TEXT NOT NULL,PRIMARY KEY(document_id,span_id));
    CREATE INDEX IF NOT EXISTS blocks_page ON document_blocks(document_id,page,ordinal);
    ''')
    conn.execute("UPDATE document_ingestions SET status='interrupted',error='服务停止，已解析页面保留，可继续解析',updated=? WHERE status IN ('queued','running')", (core.now(),))


def span_dict(row):
    return {'id': row['span_id'], 'page': row['page'], 'text': row['text'], 'kind': row['kind'], 'bbox': json.loads(row['bbox']), **json.loads(row['details'])}


def spans(doc):
    with core.db() as conn:
        cursor = conn.execute('SELECT * FROM document_blocks WHERE document_id=? ORDER BY page,ordinal', (doc['id'],))
        first = cursor.fetchone()
        if first:
            yield span_dict(first)
            for row in cursor:
                yield span_dict(row)
        else:
            yield from doc['spans']


def decorate(doc):
    with core.db() as conn:
        row = conn.execute('SELECT id,document_id,status,completed,total,profile,error FROM document_ingestions WHERE document_id=?', (doc['id'],)).fetchone()
        if not row:
            return doc
        count = conn.execute('SELECT COUNT(*) FROM document_blocks WHERE document_id=?', (doc['id'],)).fetchone()[0]
        preview = conn.execute('SELECT * FROM document_blocks WHERE document_id=? ORDER BY page,ordinal LIMIT 80', (doc['id'],)).fetchall()
    return {**doc, 'spans': [span_dict(s) for s in preview], 'span_count': count, 'ingestion': {**dict(row), 'profile': json.loads(row['profile'])}}


def document(pid, did):
    core.project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM documents WHERE id=? AND project_id=?', (did, pid)).fetchone()
    if not row:
        raise HTTPException(404, '当前项目没有这份文献')
    return {**dict(row), 'spans': json.loads(row['spans']), 'matrix': json.loads(row['matrix'])}


def job(pid, jid):
    core.project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM document_ingestions WHERE id=? AND project_id=?', (jid, pid)).fetchone()
    if not row:
        raise HTTPException(404, '解析任务不存在')
    return {**dict(row), 'profile': json.loads(row['profile'])}


def update(jid, **values):
    values['updated'] = core.now()
    with core.db() as conn:
        conn.execute('UPDATE document_ingestions SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', [json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v for v in values.values()] + [jid])


def stop_process(proc):
    """Stop this parser's descendants too, including a Windows venv launcher."""
    import psutil
    try:
        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)


def profile_for(doc, metadata):
    blocks = list(spans(doc))
    sample = '\n'.join(s['text'] for s in blocks)[:80000]
    doi = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', sample[:16000], re.I)
    arxiv = re.search(r'(?:arxiv\s*:\s*|arxiv.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v(\d+))?', '\n'.join(s['text'] for s in blocks if s['page']==1), re.I)
    headings = [{'text': s['text'], 'span_id': s['id'], 'page': s['page'], 'level': s.get('level', 1)} for s in blocks if s.get('kind') == 'heading']
    title = metadata.get('Title', '').strip()
    if not title or title.lower().endswith(('.docx', '.tex')):
        candidates = [s for s in blocks[:30] if s['page']==1 and 10<len(s['text'])<300
                      and not re.search(r'@|arxiv|copyright|permission|attribution|^abstract\b|^摘要|https?://', s['text'], re.I)]
        sizes = [s.get('font_size',0) for s in candidates]
        largest = max(sizes, default=0)
        prominent = [s for s in candidates if largest and s.get('font_size',0)>=largest*.95]
        title = ' '.join(s['text'] for s in prominent[:3]) if prominent else next((s['text'] for s in candidates if s.get('kind')=='heading'), doc['title'])
    result = {'title': title[:300], 'author': metadata.get('Author', ''), 'doi': doi[0].rstrip('.,;)') if doi else '',
        'arxiv': arxiv[1] if arxiv else '', 'version': int(arxiv[2]) if arxiv and arxiv[2] else None,
        'heading_count': len(headings), 'headings': headings, 'characters': sum(len(s['text']) for s in blocks),
        'formula_candidates': sum(bool(s.get('formula_candidate')) for s in blocks), 'duplicates': []}
    # Content similarity is a suggestion, never an automatic merge or replacement.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    others = [d for d in core.records('documents', doc['project_id']) if d['id'] != doc['id']]
    texts = [sample[:40000]] + ['\n'.join(s['text'] for s in spans(d))[:40000] for d in others]
    if len(texts) > 1 and sample.strip():
        try:
            vectors = TfidfVectorizer(analyzer='char', ngram_range=(3, 5), max_features=20000).fit_transform(texts)
            scores = cosine_similarity(vectors[:1], vectors[1:])[0]
            for other, score in zip(others, scores):
                old = other.get('ingestion', {}).get('profile', {})
                same_id = bool(result['doi'] and result['doi'].lower() == old.get('doi', '').lower() or result['arxiv'] and result['arxiv'] == old.get('arxiv'))
                if score >= .82 or same_id:
                    newer = result['version'] is not None and old.get('version') is not None and old['version'] > result['version']
                    result['duplicates'].append({'document_id': other['id'], 'title': other['title'], 'similarity': round(float(score), 3),
                        'same_identifier': same_id, 'existing_version': old.get('version'), 'suggestion': '库中版本更新，建议保留已有版本；新文件暂时并存。' if newer else '内容相近，建议核对是否同一论文或修订版本；两个文件均已保留。',
                        'scope': '正文前40000字符的三至五字片段相似度，不是完整版本差异审计。'})
        except ValueError:
            pass
    return result


def parse_job(pid, jid):
    proc = None
    try:
        record = job(pid, jid)
        if record['status'] != 'queued':
            return
        doc = document(pid, record['document_id'])
        original = core.DATA / 'documents' / doc['id'] / ('original' + Path(doc['filename']).suffix.lower())
        with core.db() as conn:
            changed = conn.execute("UPDATE document_ingestions SET status='running',error='',updated=? WHERE id=? AND status='queued'", (core.now(), jid)).rowcount
        if not changed:
            return
        started = last_page = time.monotonic()
        metadata, received = {}, queue.Queue()
        proc = subprocess.Popen([sys.executable, '-u', '-m', 'backend.pdf_worker', str(original), str(record['completed'] + 1), 'true'],
            cwd=core.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        with LOCK:
            PROCESSES[jid] = proc
        def read_lines():
            for line in proc.stdout:
                received.put(line)
            received.put(None)
        stderr = []
        def read_errors():
            for line in proc.stderr:
                stderr.append(line)
                if len(stderr) > 50:
                    stderr.pop(0)
        threading.Thread(target=read_lines, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()
        characters = 0
        with core.db() as conn:
            characters = conn.execute('SELECT COALESCE(SUM(length(text)),0) FROM document_blocks WHERE document_id=?', (doc['id'],)).fetchone()[0]
        while True:
            state = job(pid, jid)['status']
            if state not in {'queued', 'running'}:
                return
            if time.monotonic() - started > 1200 or time.monotonic() - last_page > 90:
                raise ValueError('解析超过运行预算；已完成页保留，可继续解析')
            import psutil
            try:
                worker = psutil.Process(proc.pid)
                if sum(p.memory_info().rss for p in [worker, *worker.children(recursive=True)] if p.is_running()) > 1024 * 1024 * 1024:
                    raise ValueError('解析进程内存超过1GB；已完成页保留')
            except psutil.NoSuchProcess:
                pass
            try:
                line = received.get(timeout=.3)
            except queue.Empty:
                continue
            if line is None:
                if proc.wait(timeout=5):
                    raise ValueError('PDF解析失败：' + ''.join(stderr)[-1000:])
                break
            item = json.loads(line)
            if item['type'] == 'metadata':
                metadata = item['metadata']
                continue
            last_page = time.monotonic()
            characters += sum(len(b['text']) for b in item['blocks'])
            if characters > 4000000:
                raise ValueError('本文超过400万字符解析预算，请拆分章节后导入')
            with core.db() as conn:
                # Page + blocks + progress commit together; resumptions never rewrite cited pages.
                conn.execute('INSERT INTO document_pages VALUES (?,?,?,?,?,?)', (doc['id'], item['page'], item['width'], item['height'], item['method'], json.dumps({k: v for k, v in item.items() if k not in {'blocks', 'type'}}, ensure_ascii=False)))
                for n, block in enumerate(item['blocks']):
                    details = {k: v for k, v in block.items() if k not in {'id', 'page', 'text', 'kind', 'bbox'}}
                    conn.execute('INSERT INTO document_blocks VALUES (?,?,?,?,?,?,?,?)', (doc['id'], block['id'], item['page'], n, block['kind'], block['text'], json.dumps(block['bbox']), json.dumps(details)))
                conn.execute('UPDATE document_ingestions SET completed=?,updated=? WHERE id=?', (item['page'], core.now(), jid))
        profile = profile_for(doc, metadata)
        if not profile['characters']:
            raise ValueError('没有识别到文字；原文件已保留，请检查扫描清晰度或文件内容')
        with core.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            saved = conn.execute('SELECT profile FROM document_ingestions WHERE id=?', (jid,)).fetchone()
            source_metadata = json.loads(saved['profile']).get('metadata_source') if saved else None
            if source_metadata:
                profile['parsed_title'] = profile['title']
                profile['title'] = source_metadata['title'][:300]
                profile['parsed_arxiv'] = profile['arxiv']
                identifier = re.fullmatch(r'(.+?)(?:v(\d+))?', source_metadata.get('arxiv_id', ''))
                if identifier:
                    profile['arxiv'] = identifier[1]
                    profile['version'] = int(identifier[2]) if identifier[2] else None
                profile['metadata_source'] = source_metadata
            conn.execute('UPDATE documents SET title=? WHERE id=?', (profile['title'], doc['id']))
            conn.execute("UPDATE document_ingestions SET status='completed',profile=?,updated=? WHERE id=?", (json.dumps(profile, ensure_ascii=False), core.now(), jid))
    except Exception as exc:
        try:
            if job(pid, jid)['status'] != 'cancelled':
                update(jid, status='failed', error=str(exc)[:1500])
        except HTTPException:
            pass  # Project/document was removed while parsing.
    finally:
        if proc:
            stop_process(proc)
        with LOCK:
            PROCESSES.pop(jid, None)


@router.post('/projects/{pid}/document-ingestions')
async def ingest(pid: str, file: UploadFile = File(...)):
    core.project(pid)
    content = await file.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024:
        raise HTTPException(413, '结构化PDF最大32MB')
    filename = Path(file.filename or 'document.pdf').name
    if Path(filename).suffix.lower() != '.pdf':
        raise HTTPException(422, '结构化解析接收PDF；文本与Markdown使用文献库普通导入')
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise HTTPException(422, '请先解密PDF再导入')
        total = len(reader.pages)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, '无法打开这份PDF，请检查文件是否完整')
    if not 1 <= total <= 2000:
        raise HTTPException(422, '结构化解析支持1—2000页，按页处理并限制运行资源')
    did, jid, created = core.uid(), core.uid(), core.now()
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT COUNT(*) FROM document_ingestions WHERE status IN ('queued','running')").fetchone()[0] >= 6:
            raise HTTPException(429, '已有6份文献等待解析，请等待或停止其中的任务')
        conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)', (did, pid, Path(filename).stem, filename, total, '[]', '{}', created))
        conn.execute('INSERT INTO document_ingestions VALUES (?,?,?,?,?,?,?,?,?,?)', (jid, pid, did, 'queued', 0, total, '{}', '', created, created))
    original = core.DATA / 'documents' / did
    original.mkdir(parents=True, exist_ok=True)
    (original / 'original.pdf').write_bytes(content)
    POOL.submit(parse_job, pid, jid)
    return job(pid, jid)


@router.get('/projects/{pid}/document-ingestions')
def list_jobs(pid: str):
    core.project(pid)
    with core.db() as conn:
        rows = conn.execute('SELECT id FROM document_ingestions WHERE project_id=? ORDER BY created DESC LIMIT 50', (pid,)).fetchall()
    return [job(pid, r['id']) for r in rows]


@router.get('/projects/{pid}/document-ingestions/{jid}')
def get_job(pid: str, jid: str):
    return job(pid, jid)


@router.post('/projects/{pid}/document-ingestions/{jid}/cancel')
def cancel_job(pid: str, jid: str):
    record = job(pid, jid)
    if record['status'] in {'queued', 'running'}:
        update(jid, status='cancelled', error='作者停止解析，已完成的页面保留')
    return job(pid, jid)


@router.post('/projects/{pid}/document-ingestions/{jid}/resume')
def resume_job(pid: str, jid: str):
    record = job(pid, jid)
    if record['status'] not in {'cancelled', 'interrupted', 'failed'}:
        raise HTTPException(409, '只有已停止或中断的解析任务可以继续')
    with LOCK:
        if jid in PROCESSES:
            raise HTTPException(409, '上次解析进程正在退出，请稍后继续')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT COUNT(*) FROM document_ingestions WHERE status IN ('queued','running')").fetchone()[0] >= 6:
            raise HTTPException(429, '解析队列已满，请稍后继续')
        changed = conn.execute("UPDATE document_ingestions SET status='queued',error='',updated=? WHERE id=? AND status IN ('cancelled','interrupted','failed')", (core.now(), jid)).rowcount
    if changed:
        POOL.submit(parse_job, pid, jid)
    return job(pid, jid)


@router.get('/projects/{pid}/documents/{did}/spans')
def get_spans(pid: str, did: str, page: int = Query(default=1, ge=1), anchor: str = '', limit: int = Query(default=200, ge=1, le=300), offset: int = Query(default=0, ge=0)):
    doc = document(pid, did)
    if anchor:
        found = next((s for s in spans(doc) if s['id'] == anchor), None)
        if not found:
            raise HTTPException(404, '原文片段不存在')
        page = found['page']
        with core.db() as conn:
            position = conn.execute('SELECT ordinal FROM document_blocks WHERE document_id=? AND span_id=?', (did, anchor)).fetchone()
        if position:
            offset = position['ordinal'] // limit * limit
        else:
            page_ids = [s['id'] for s in doc['spans'] if s['page'] == page]
            offset = page_ids.index(anchor) // limit * limit
    if page > doc['pages']:
        raise HTTPException(422, '页码超过文献范围')
    with core.db() as conn:
        indexed = conn.execute('SELECT 1 FROM document_pages WHERE document_id=? LIMIT 1', (did,)).fetchone()
        if indexed:
            total = conn.execute('SELECT COUNT(*) FROM document_blocks WHERE document_id=? AND page=?', (did, page)).fetchone()[0]
            rows = conn.execute('SELECT * FROM document_blocks WHERE document_id=? AND page=? ORDER BY ordinal LIMIT ? OFFSET ?', (did, page, limit, offset)).fetchall()
            items = [span_dict(r) for r in rows]
        else:
            items = [s for s in doc['spans'] if s['page'] == page]
            total, items = len(items), items[offset:offset + limit]
        details = conn.execute('SELECT details FROM document_pages WHERE document_id=? AND page=?', (did, page)).fetchone()
    return {'items': items, 'page': page, 'pages': doc['pages'], 'total': total, 'offset': offset, 'has_more': offset + len(items) < total, 'details': json.loads(details['details']) if details else None}


@router.get('/projects/{pid}/documents/{did}/page-image/{page}')
def page_image(pid: str, did: str, page: int):
    doc = document(pid, did)
    if not 1 <= page <= doc['pages'] or not doc['filename'].lower().endswith('.pdf'):
        raise HTTPException(422, '请选择PDF的有效页码')
    original = core.DATA / 'documents' / did / 'original.pdf'
    if not original.is_file():
        raise HTTPException(404, '旧资料没有保存原文件，请重新导入')
    # Render only the current page; no browser PDF script execution or external request.
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(original) as pdf:
        pdf_page = pdf[page - 1]
        bitmap = pdf_page.render(scale=min(1.5, 1600 / max(pdf_page.get_size())))
        image = bitmap.to_pil()
        memory = io.BytesIO()
        image.save(memory, format='PNG')
        image.close()
        bitmap.close()
        pdf_page.close()
    return Response(memory.getvalue(), media_type='image/png', headers={'Cache-Control': 'private, max-age=300'})
