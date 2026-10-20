from pathlib import Path
import sqlite3
import uuid

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
app = FastAPI(title='研舟 · 科研工作台')


def db():
    conn = sqlite3.connect(DATA / 'workbench.sqlite3')
    conn.row_factory = sqlite3.Row
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


if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
