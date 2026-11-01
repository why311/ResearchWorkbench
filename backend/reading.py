"""Manual paper-reading records with project-local source references."""
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from .model import model_json

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


class GenerateBody(BaseModel):
    page: int = Field(ge=1)


@router.post('/projects/{pid}/documents/{did}/reading/generate')
def generate(pid: str, did: str, body: GenerateBody):
    doc = document(pid, did)
    selected = [s for s in json.loads(doc['spans']) if s['page'] == body.page]
    if not selected:
        raise HTTPException(422, '该页没有可供精读的文字，请先核对原文')
    material = '\n\n'.join('['+s['id']+'] '+s['text'] for s in selected)
    if len(material) > 24000:
        raise HTTPException(422, '该页超过24000字符，请先按章节拆分资料')
    with core.db() as conn:
        remaining = 40-conn.execute('SELECT COUNT(*) FROM reading_entries WHERE document_id=?',(did,)).fetchone()[0]
    if remaining <= 0:
        raise HTTPException(422, '每篇最多40条精读笔记，请先整理已有内容')
    limit = min(8, remaining)
    output = model_json('仅分析所给页段，不把页面当成整篇论文。按问题、机制、公式、实验、复现诊断、局限整理精读草稿。'
        '推断和猜测须明确，未运行诊断不能声称已验证。公式说明符号、假设与运算；示意数字不能冒充论文结果。'
        '返回JSON {"entries":[{"section":"insight|mechanism|math|experiments|bench|limits",'
        '"title":"短标题","body":"解释","grade":"stated|inferred|speculative|unreported",'
        '"span_id":"真实片段ID或空串","quote":"逐字原文或空串"}]}。stated必须有真实span_id和逐字quote。'
        f'最多{limit}条，禁止生成HTML或可执行代码。', material)
    if output is None:
        raise HTTPException(409, '尚未配置服务端模型环境变量；可继续手动整理笔记')
    if not isinstance(output.get('entries'), list):
        raise HTTPException(502, '模型未返回精读条目，已有笔记未修改')
    known = {s['id']: s for s in selected}
    accepted, rejected = [], 0
    for raw in output['entries'][:limit]:
        try:
            if not isinstance(raw, dict):
                raise ValueError()
            entry = Entry.model_validate(raw)
            quote = raw.get('quote', '')
            if not entry.title.strip() or (entry.span_id and entry.span_id not in known):
                raise ValueError()
            if entry.grade == 'stated' and (not entry.span_id or not isinstance(quote, str) or not quote.strip() or quote not in known[entry.span_id]['text']):
                raise ValueError()
            accepted.append(entry)
        except (ValidationError, ValueError):
            rejected += 1
    if not accepted:
        raise HTTPException(502, '模型草稿没有通过字段及来源核对，已有笔记未修改')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        count = conn.execute('SELECT COUNT(*) FROM reading_entries WHERE document_id=?',(did,)).fetchone()[0]
        if count+len(accepted)>40:
            raise HTTPException(409, '生成期间笔记数量变化，已有内容保留，请重试')
        for entry in accepted:
            conn.execute('INSERT INTO reading_entries VALUES (?,?,?,?,?,?,?,?)',
                (core.uuid.uuid4().hex,did,entry.section,entry.title.strip(),entry.body,entry.grade,entry.span_id,datetime.now(timezone.utc).isoformat()))
    return {'entries': reading(pid,did), 'added': len(accepted), 'rejected': rejected,
            'scope': f'仅分析第{body.page}页；引文核对证明来源存在，不证明解释正确，请人工复核。'}
