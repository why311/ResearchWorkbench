"""Editable Markdown drafts with project-local source references."""
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app as core
from .translations import passage

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.execute('''CREATE TABLE IF NOT EXISTS writing_drafts(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        title TEXT NOT NULL, template TEXT NOT NULL, citations TEXT NOT NULL,
        updated TEXT NOT NULL)''')


class Citation(BaseModel):
    alias: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    document_id: str
    span_id: str


class DraftEdit(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    template: str = Field(min_length=1, max_length=200000)


class DraftBody(DraftEdit):
    citations: list[Citation] = Field(default_factory=list, max_length=40)


@router.get('/projects/{pid}/writing-drafts')
def list_drafts(pid: str):
    core.project(pid)
    with core.db() as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id,title,updated FROM writing_drafts WHERE project_id=? ORDER BY updated DESC,id', (pid,))]


@router.get('/projects/{pid}/writing-drafts/{did}')
def get_draft(pid: str, did: str):
    core.project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM writing_drafts WHERE id=? AND project_id=?', (did, pid)).fetchone()
    if not row:
        raise HTTPException(404, '草稿不存在')
    return dict(row) | {'citations': json.loads(row['citations'])}


def create_draft(pid: str, body: DraftBody):
    core.project(pid)
    for citation in body.citations:
        passage(pid, citation.document_id, citation.span_id)
    did = core.uid()
    with core.db() as conn:
        conn.execute('INSERT INTO writing_drafts VALUES (?,?,?,?,?,?)', (
            did, pid, body.title, body.template,
            json.dumps([citation.model_dump() for citation in body.citations]), core.now()))
    return get_draft(pid, did)


@router.put('/projects/{pid}/writing-drafts/{did}')
def edit_draft(pid: str, did: str, body: DraftEdit):
    get_draft(pid, did)
    if not body.title.strip() or not body.template.strip():
        raise HTTPException(422, '请填写标题和正文')
    with core.db() as conn:
        conn.execute('UPDATE writing_drafts SET title=?,template=?,updated=? WHERE id=? AND project_id=?',
                     (body.title.strip(), body.template, core.now(), did, pid))
    return get_draft(pid, did)


@router.get('/projects/{pid}/writing-drafts/{did}/export')
def export_draft(pid: str, did: str):
    from .documents import document

    draft = get_draft(pid, did)
    citations = {citation['alias']: citation for citation in draft['citations']}
    references = {}

    def cite(match):
        alias = match.group(1)
        if alias not in citations:
            return '（待补来源）'
        if alias not in references:
            citation = citations[alias]
            source = passage(pid, citation['document_id'], citation['span_id'])
            title = document(pid, citation['document_id'])['title']
            quote = '\n'.join('> ' + line for line in source['text'].splitlines())
            number = len(references) + 1
            references[alias] = (number, f"{number}. {title} · 第{source['page']}页 · {source['id']}\n\n{quote}")
        return f"[{references[alias][0]}]"

    text = '# ' + draft['title'] + '\n\n' + re.sub(r'\[\[cite:([^\]]+)\]\]', cite, draft['template'])
    if references:
        text += '\n\n## 文献原文依据\n\n' + '\n\n'.join(entry for _, entry in references.values())
    return Response(text + '\n', media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="research-draft.md"'})
