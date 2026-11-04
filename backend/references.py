"""Project-local reference candidates, source review and document links."""
import json
import re
import uuid
from typing import Literal
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from . import app as core
from .documents import document, project
from .translations import now, spans

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS literature_references(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,span_id TEXT NOT NULL,identifier TEXT NOT NULL,label TEXT NOT NULL,quote TEXT NOT NULL,status TEXT NOT NULL,target_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,created TEXT NOT NULL,updated TEXT NOT NULL,UNIQUE(document_id,identifier))")

DOI = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I)
ARXIV = re.compile(r'(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?)', re.I)


def identifiers(text):
    found = []
    for match in DOI.finditer(text):
        value = match.group().rstrip('.,;:')
        while value.endswith(')') and value.count(')') > value.count('('):
            value = value[:-1]
        found.append(('doi:' + value.lower(), match.start(), match.start() + len(value)))
    for match in ARXIV.finditer(text):
        value = re.sub(r'v\d+$', '', match.group(1), flags=re.I).lower()
        found.append(('arxiv:' + value, match.start(), match.end()))
    return found


class ReferencesBody(BaseModel):
    start_page: int = Field(ge=1, le=2000)
    end_page: int = Field(ge=1, le=2000)


@router.post('/projects/{pid}/documents/{did}/references-extract')
def extract_references(pid: str, did: str, body: ReferencesBody):
    doc = document(pid, did)
    if not body.start_page <= body.end_page <= doc['pages'] or body.end_page - body.start_page >= 30:
        raise HTTPException(422, '请选择最多30页的有效参考文献范围')
    selected = [s for s in spans(doc) if body.start_page <= s['page'] <= body.end_page]
    if sum(len(s['text']) for s in selected) > 200000:
        raise HTTPException(422, '选定范围超过200000字符，请缩小参考文献页范围')
    candidates = {}
    for span in selected:
        for identifier, start, end in identifiers(span['text']):
            excerpt = span['text'][max(0, start - 160):min(len(span['text']), end + 160)]
            candidates.setdefault(identifier, (span['id'], excerpt))
    if len(candidates) > 300:
        raise HTTPException(422, '本轮超过300个标识，请缩小范围后分批提取')
    created = 0
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        count = conn.execute('SELECT COUNT(*) FROM literature_references WHERE document_id=?', (did,)).fetchone()[0]
        existing = {r[0] for r in conn.execute('SELECT identifier FROM literature_references WHERE document_id=?', (did,))}
        if count + len(candidates.keys() - existing) > 1000:
            raise HTTPException(422, '单篇文献最多保存1000条引用候选，请先整理已有记录')
        for identifier, (sid, excerpt) in candidates.items():
            created += conn.execute('INSERT INTO literature_references VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id,identifier) DO NOTHING', (uuid.uuid4().hex, pid, did, sid, identifier, identifier, excerpt, 'candidate', None, now(), now())).rowcount
    return {'created': created, 'found': len(candidates), 'message': '仅从作者指定页范围识别DOI/arXiv候选；出现在该页不自动证明引用关系，需逐条核对。'}


def reference(pid, rid):
    project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM literature_references WHERE id=? AND project_id=?', (rid, pid)).fetchone()
    if not row:
        raise HTTPException(404, '引用记录不存在')
    return dict(row)


class ReferenceBody(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    status: Literal['candidate', 'confirmed'] = 'candidate'
    target_document_id: str | None = None


@router.put('/projects/{pid}/references/{rid}')
def update_reference(pid: str, rid: str, body: ReferenceBody):
    row = reference(pid, rid)
    if not body.label.strip():
        raise HTTPException(422, '请填写被引文献名称或保留标识')
    if body.target_document_id:
        document(pid, body.target_document_id)
        if body.target_document_id == row['document_id']:
            raise HTTPException(422, '不能把被引文献关联到来源文献自身')
    with core.db() as conn:
        conn.execute('UPDATE literature_references SET label=?,status=?,target_document_id=?,updated=? WHERE id=?', (body.label.strip(), body.status, body.target_document_id, now(), rid))
    return reference(pid, rid)


@router.delete('/projects/{pid}/references/{rid}')
def remove_reference(pid: str, rid: str):
    row = reference(pid, rid)
    with core.db() as conn:
        conn.execute('DELETE FROM literature_references WHERE id=?', (rid,))
    return row


@router.get('/projects/{pid}/reference-network')
def network(pid: str):
    project(pid)
    with core.db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM literature_references WHERE project_id=? ORDER BY created,id', (pid,))]
        docs = [dict(r) for r in conn.execute('SELECT id,title FROM documents WHERE project_id=?', (pid,))]
    for row in rows:
        row['url'] = ('https://doi.org/' + quote(row['identifier'][4:], safe='/') if row['identifier'].startswith('doi:') else 'https://arxiv.org/abs/' + quote(row['identifier'][6:], safe='/') if row['identifier'].startswith('arxiv:') else '')
    positions = {}
    for row in rows:
        did = row['document_id']
        if did not in positions:
            counts, positions[did] = {}, {}
            for span in spans(document(pid, did)):
                index = counts.get(span['page'], 0)
                positions[did][span['id']] = {'page': span['page'], 'offset': index // 100 * 100}
                counts[span['page']] = index + 1
        row['source'] = positions[did].get(row['span_id'])
    return {'documents': docs, 'references': rows, 'scope': '仅为本项目提取并由作者核对的引用关系；不是全网被引统计，也不表示论文质量或研究新颖性。'}


@router.get('/projects/{pid}/reference-network/export')
def export_network(pid: str):
    return Response(json.dumps(network(pid), ensure_ascii=False, indent=2), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="reference-network.json"'})
