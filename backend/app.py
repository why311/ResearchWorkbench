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


from .documents import router as documents_router
app.include_router(documents_router)

if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
