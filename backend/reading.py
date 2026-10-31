"""Manual paper-reading records with project-local source references."""
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app as core
from .documents import document

router = APIRouter(prefix='/api')
SECTIONS = {'insight':'问题与洞见','mechanism':'机制与设定','math':'公式与手算','experiments':'实验与证据','bench':'复现诊断','limits':'局限与下一步'}
GRADES = {'stated':'原文有据','inferred':'推断','speculative':'猜测','unreported':'本次材料未找到'}
with core.db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS reading_entries(id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,section TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,grade TEXT NOT NULL,span_id TEXT NOT NULL,updated TEXT NOT NULL)')


class Entry(BaseModel):
    section: Literal['insight','mechanism','math','experiments','bench','limits']
    title: str = Field(min_length=1,max_length=120)
    body: str = Field(default='',max_length=8000)
    grade: Literal['stated','inferred','speculative','unreported'] = 'inferred'
    span_id: str = ''


@router.get('/projects/{pid}/documents/{did}/reading')
def reading(pid: str,did: str):
    doc = document(pid,did)
    source = {s['id']:s for s in json.loads(doc['spans'])}
    with core.db() as conn:
        rows = conn.execute('SELECT * FROM reading_entries WHERE document_id=? ORDER BY rowid',(did,)).fetchall()
    return [{**dict(row),'source':source.get(row['span_id'])} for row in rows]


def write_entry(pid,did,body,eid=None):
    doc = document(pid,did)
    if not body.title.strip():
        raise HTTPException(422,'请填写笔记标题')
    if body.span_id and not any(s['id']==body.span_id for s in json.loads(doc['spans'])):
        raise HTTPException(422,'引用片段不属于这篇文献')
    if body.grade=='stated' and not body.span_id:
        raise HTTPException(422,'原文有据的笔记需要关联原文片段')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if eid:
            if not conn.execute('SELECT 1 FROM reading_entries WHERE id=? AND document_id=?',(eid,did)).fetchone():
                raise HTTPException(404,'笔记不存在')
        else:
            if conn.execute('SELECT COUNT(*) FROM reading_entries WHERE document_id=?',(did,)).fetchone()[0]>=40:
                raise HTTPException(422,'每篇最多40条精读笔记，请先整理已有内容')
            eid=core.uuid.uuid4().hex
        conn.execute('INSERT INTO reading_entries VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET section=excluded.section,title=excluded.title,body=excluded.body,grade=excluded.grade,span_id=excluded.span_id,updated=excluded.updated',
                     (eid,did,body.section,body.title.strip(),body.body,body.grade,body.span_id,datetime.now(timezone.utc).isoformat()))
    return reading(pid,did)


@router.post('/projects/{pid}/documents/{did}/reading')
def create(pid: str,did: str,body: Entry):
    return write_entry(pid,did,body)


@router.put('/projects/{pid}/documents/{did}/reading/{eid}')
def update(pid: str,did: str,eid: str,body: Entry):
    return write_entry(pid,did,body,eid)


@router.get('/projects/{pid}/documents/{did}/reading.md')
def export(pid: str,did: str):
    doc=document(pid,did)
    lines=['# '+doc['title']+' 精读笔记','原文定位用于核对来源，作者解释与推断需另行核实。']
    for entry in reading(pid,did):
        lines += ['## '+SECTIONS[entry['section']]+' · '+entry['title'],GRADES[entry['grade']],entry['body']]
        if entry['source']:
            s=entry['source'];lines += [f"原文 第{s['page']}页 · {s['id']}",s['text']]
        lines += ['保存时间 '+entry['updated']]
    return Response('\n\n'.join(lines)+'\n',media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="paper-reading.md"'})
