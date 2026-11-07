"""Research decisions and bounded, paired-seed experiment comparisons."""
import io
import json
from typing import Literal
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app as core

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS research_notes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT NOT NULL,hypothesis TEXT NOT NULL,prediction TEXT NOT NULL,outcome TEXT NOT NULL,decision TEXT NOT NULL,source_refs TEXT NOT NULL,run_ids TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL)")


def item(table, pid, rid):
    core.project(pid)
    result = next((r for r in core.records(table, pid) if r['id'] == rid), None)
    if result is None:
        raise HTTPException(404, '研究记录不存在')
    return result


class SourceRef(BaseModel):
    document_id: str
    span_id: str


class NoteBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    hypothesis: str = Field(default='', max_length=4000)
    prediction: str = Field(default='', max_length=4000)
    outcome: Literal['planned', 'testing', 'supported', 'unsupported', 'inconclusive'] = 'planned'
    decision: str = Field(default='', max_length=6000)
    source_refs: list[SourceRef] = Field(default_factory=list, max_length=20)
    run_ids: list[str] = Field(default_factory=list, max_length=30)


def resolve_note(pid, note):
    documents = {d['id']: d for d in core.records('documents', pid)}
    sources = []
    for ref in note['source_refs']:
        document = documents.get(ref['document_id'])
        span = next((s for s in core.document_spans(document) if s['id'] == ref['span_id']), None) if document else None
        if span is None:
            raise HTTPException(422, '文献片段不属于当前项目或已失效')
        sources.append({**ref, 'title': document['title'], 'page': span['page'], 'text': span['text']})
    if note['run_ids']:
        raise HTTPException(422, '实验结果将在实验与分析阶段接入')
    runs, linked_reports = [], []
    gaps = []
    if not sources:
        gaps.append('尚未关联原文片段')
    if not any(r['status'] == 'succeeded' for r in runs):
        gaps.append('尚未关联成功运行的结果')
    if not note['prediction'].strip():
        gaps.append('尚未写下可检验的预期')
    if note['outcome'] in {'supported', 'unsupported', 'inconclusive'} and not note['decision'].strip():
        gaps.append('尚未记录判断理由')
    return {**note, 'sources': sources, 'runs': runs, 'linked_reports': linked_reports, 'gaps': gaps}


def validate_note(pid, body):
    value = body.model_dump()
    if not value['title'].strip():
        raise HTTPException(422, '请填写研究设想标题')
    if len(set(value['run_ids'])) != len(value['run_ids']) or len({(r['document_id'], r['span_id']) for r in value['source_refs']}) != len(value['source_refs']):
        raise HTTPException(422, '来源引用不能重复')
    resolve_note(pid, value)
    return value


@router.post('/projects/{pid}/research-notes')
def create_note(pid: str, body: NoteBody):
    core.project(pid)
    value = validate_note(pid, body)
    nid, created = core.uid(), core.now()
    with core.db() as conn:
        conn.execute('INSERT INTO research_notes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (nid, pid, value['title'].strip(), value['hypothesis'], value['prediction'], value['outcome'], value['decision'],
             json.dumps(value['source_refs']), json.dumps(value['run_ids']), created, created))
    return get_note(pid, nid)


@router.put('/projects/{pid}/research-notes/{nid}')
def update_note(pid: str, nid: str, body: NoteBody):
    item('research_notes', pid, nid)
    value = validate_note(pid, body)
    with core.db() as conn:
        conn.execute('UPDATE research_notes SET title=?,hypothesis=?,prediction=?,outcome=?,decision=?,source_refs=?,run_ids=?,updated=? WHERE id=?',
            (value['title'].strip(), value['hypothesis'], value['prediction'], value['outcome'], value['decision'],
             json.dumps(value['source_refs']), json.dumps(value['run_ids']), core.now(), nid))
    return get_note(pid, nid)


@router.get('/projects/{pid}/research-notes/{nid}')
def get_note(pid: str, nid: str):
    return resolve_note(pid, item('research_notes', pid, nid))


@router.get('/projects/{pid}/research-notes/{nid}/export')
def export_note(pid: str, nid: str):
    note = get_note(pid, nid)
    outcomes = {'planned': '待验证', 'testing': '验证中', 'supported': '作者判断支持', 'unsupported': '作者判断不支持', 'inconclusive': '证据不足'}
    text = f"# {note['title']}\n\n## 研究设想\n\n{note['hypothesis']}\n\n## 可检验预期\n\n{note['prediction']}\n\n## 作者判断\n\n{outcomes[note['outcome']]}\n\n{note['decision']}\n\n"
    text += '## 原文来源\n\n' + '\n\n'.join(f"### {s['title']} · 第{s['page']}页 · {s['span_id']}\n\n{s['text']}" for s in note['sources'])
    text += '\n\n## 实际运行\n\n' + '\n\n'.join(f"- {r['name']} · {r['id']} · {r['status']}\n  指标：{json.dumps(r['metrics'], ensure_ascii=False)}\n  参数：{json.dumps(r['config'], ensure_ascii=False)}" for r in note['runs'])
    text += '\n\n## 成果引用\n\n' + '\n'.join(f"- {r['title']} · {r['sync_status']} · 已生成版本{r['generated'].get('version', 0)}" for r in note['linked_reports'])
    text += '\n\n## 尚待补充\n\n' + '\n'.join('- ' + gap for gap in note['gaps'])
    text += '\n\n判断由作者填写；运行结果和引用不能自动证明因果、显著性或研究新颖性。\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('research-note.md', text)
        archive.writestr('sources.json', json.dumps(note, ensure_ascii=False, indent=2))
    return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="research-note.zip"'})
