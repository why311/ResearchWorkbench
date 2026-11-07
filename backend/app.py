from pathlib import Path
import sqlite3
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
app = FastAPI(title='研舟 · 科研工作台')


def db():
    conn = sqlite3.connect(DATA / 'workbench.sqlite3')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


with db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,question TEXT NOT NULL)')


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    question: str = Field(default='', max_length=2000)


@app.get('/api/health')
def health():
    return {'ok': True}


@app.get('/api/projects')
def projects():
    with db() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM projects ORDER BY rowid DESC')]


@app.post('/api/projects')
def create_project(body: ProjectBody):
    from fastapi import HTTPException
    if not body.name.strip():
        raise HTTPException(422, '请填写项目名称')
    value = {'id': uuid.uuid4().hex, 'name': body.name.strip(), 'question': body.question.strip()}
    with db() as conn:
        conn.execute('INSERT INTO projects VALUES (?,?,?)', tuple(value.values()))
    return value


@app.middleware('http')
async def local_origin(request, call_next):
    origin = request.headers.get('origin')
    try:
        parsed = urlparse(origin) if origin else None
        allowed = not parsed or (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'} and (parsed.netloc == request.url.netloc or parsed.port == 5178))
    except ValueError:
        allowed = False
    if not allowed:
        return JSONResponse({'detail': '仅允许本机工作台页面访问'}, status_code=403)
    return await call_next(request)


from datetime import datetime, timezone
import json
from contextlib import asynccontextmanager

def now():
    return datetime.now(timezone.utc).isoformat()

def uid():
    return uuid.uuid4().hex

def project(pid):
    from .documents import project as get_project
    return get_project(pid)

def records(table, pid):
    if table == 'research_notes':
        with db() as conn:
            return [dict(row) | {'source_refs': json.loads(row['source_refs']), 'run_ids': json.loads(row['run_ids'])}
                    for row in conn.execute('SELECT * FROM research_notes WHERE project_id=? ORDER BY created DESC', (pid,))]
    if table != 'documents':
        raise ValueError('Only documents are available in this publication stage')
    from .ingestion import document, decorate
    with db() as conn:
        ids = [row[0] for row in conn.execute('SELECT id FROM documents WHERE project_id=? ORDER BY rowid DESC', (pid,))]
    return [decorate(document(pid, did)) for did in ids]

from .model import model_json, settings

from .documents import router as documents_router
app.include_router(documents_router)
from .evidence import router as evidence_router
app.include_router(evidence_router)
from .reading import router as reading_router
app.include_router(reading_router)

from .translations import router as translations_router
app.include_router(translations_router)

from .references import router as references_router
app.include_router(references_router)

from .ingestion import router as ingestion_router, decorate as decorate_document, spans as document_spans
app.include_router(ingestion_router)
from .discovery import router as discovery_router
app.include_router(discovery_router)
from .paper_watch import router as watch_router
app.include_router(watch_router)
from .graph_insights import router as graph_router
app.include_router(graph_router)
from .reference_downloads import router as download_router
app.include_router(download_router)

from .semantic import router as semantic_router
app.include_router(semantic_router)
from .research import router as research_router
app.include_router(research_router)
from .assistant import router as assistant_router
app.include_router(assistant_router)
from .writing_drafts import router as writing_router
app.include_router(writing_router)
from .research_completion import router as synthesis_router
app.include_router(synthesis_router)

@app.get('/api/research-model-status')
def research_model_status():
    config = settings()
    return {'configured': bool(config['base_url'] and config['model'])}


@asynccontextmanager
async def stage_lifespan(_app):
    from .paper_watch import start_scheduler
    from .ingestion import LOCK, PROCESSES, stop_process
    stop = start_scheduler()
    yield
    stop.set()
    with db() as conn:
        conn.execute("UPDATE document_ingestions SET status='interrupted',error='服务停止，可继续解析' WHERE status IN ('queued','running')")
        conn.execute("UPDATE reference_downloads SET status='interrupted',updated=? WHERE status IN ('queued','running')", (now(),))
        conn.execute("UPDATE research_tasks SET status='interrupted',error='服务停止，已完成的工具记录保留',updated=? WHERE status IN ('queued','running')", (now(),))
        conn.execute("UPDATE semantic_indexes SET status='interrupted',error='服务停止，请重新建立索引' WHERE status IN ('queued','running')")
    with LOCK:
        for child in PROCESSES.values():
            if child.poll() is None:
                stop_process(child)

app.router.lifespan_context = stage_lifespan

if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
