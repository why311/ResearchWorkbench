"""First literature stage: original files, page-aware text and project ownership."""
import io
import json
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pypdf import PdfReader
from pydantic import BaseModel, Field

from . import app as core

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT NOT NULL,filename TEXT NOT NULL,pages INTEGER NOT NULL,spans TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS annotations(document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,span_id TEXT NOT NULL,kind TEXT NOT NULL,note TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(document_id,span_id))')


def project(pid):
    with core.db() as conn:
        row = conn.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if not row:
        raise HTTPException(404, '项目不存在')
    return dict(row)


def document(pid, did):
    project(pid)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM documents WHERE id=? AND project_id=?', (did, pid)).fetchone()
    if not row:
        raise HTTPException(404, '这篇文献不属于当前项目')
    return dict(row)


@router.get('/projects/{pid}')
def project_detail(pid: str):
    value = project(pid)
    with core.db() as conn:
        rows = conn.execute('SELECT id,title,filename,pages,spans FROM documents WHERE project_id=? ORDER BY rowid DESC', (pid,)).fetchall()
    value['documents'] = [{k: r[k] for k in ('id', 'title', 'filename', 'pages')} | {'span_count': len(json.loads(r['spans']))} for r in rows]
    return value


@router.post('/projects/{pid}/documents')
async def upload(pid: str, file: UploadFile = File(...)):
    project(pid)
    content = await file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, '单篇资料最大20MB')
    filename = Path(file.filename or 'document').name
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == '.pdf':
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 300:
                raise HTTPException(422, '当前阶段支持300页以内PDF')
            pages = [(i + 1, p.extract_text() or '') for i, p in enumerate(reader.pages)]
        elif suffix in {'.md', '.txt'}:
            pages = [(1, content.decode('utf-8-sig'))]
        else:
            raise HTTPException(422, '支持PDF、UTF-8文本和Markdown')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, '无法读取资料，请检查文件格式和编码')
    if sum(len(text) for _, text in pages) > 1000000:
        raise HTTPException(422, '当前阶段支持100万字符以内的原文')
    spans = []
    for page, text in pages:
        for paragraph in re.split(r'\n\s*\n', re.sub(r'[ \t]+', ' ', text).strip()):
            for offset in range(0, len(paragraph), 1600):
                piece = paragraph[offset:offset + 1600]
                if piece.strip():
                    spans.append({'id': f'p{page}-s{len(spans) + 1}', 'page': page, 'text': piece})
    if not spans:
        raise HTTPException(422, '没有提取到文字；本阶段尚不含扫描页OCR，请导入可提取文字的资料')
    did = uuid.uuid4().hex
    folder = core.DATA / 'documents' / did
    folder.mkdir(parents=True)
    (folder / ('original' + suffix)).write_bytes(content)
    with core.db() as conn:
        conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?)', (did, pid, Path(filename).stem, filename, len(pages), json.dumps(spans, ensure_ascii=False)))
    return {'id': did, 'title': Path(filename).stem, 'pages': len(pages), 'span_count': len(spans)}


@router.get('/projects/{pid}/documents/{did}')
def read_document(pid: str, did: str, page: int = Query(default=1, ge=1), offset: int = Query(default=0, ge=0)):
    doc = document(pid, did)
    if page > doc['pages']:
        raise HTTPException(422, '页码超出资料范围')
    all_spans = [s for s in json.loads(doc['spans']) if s['page'] == page]
    return {'id': did, 'title': doc['title'], 'pages': doc['pages'], 'page': page, 'offset': offset, 'total': len(all_spans), 'items': all_spans[offset:offset + 100], 'has_more': offset + 100 < len(all_spans)}


@router.get('/projects/{pid}/documents/{did}/original')
def original(pid: str, did: str):
    doc = document(pid, did)
    suffix = Path(doc['filename']).suffix.lower()
    path = core.DATA / 'documents' / did / ('original' + suffix)
    if not path.is_file():
        raise HTTPException(404, '原文件不存在')
    return FileResponse(path, filename=doc['filename'])


class AnnotationBody(BaseModel):
    span_id: str
    kind: Literal['highlight', 'confused', 'understood'] = 'highlight'
    note: str = Field(default='', max_length=4000)


@router.get('/projects/{pid}/documents/{did}/annotations')
def annotations(pid: str, did: str):
    doc = document(pid, did)
    spans = {s['id']: s for s in json.loads(doc['spans'])}
    with core.db() as conn:
        rows = conn.execute('SELECT * FROM annotations WHERE document_id=? ORDER BY updated,span_id', (did,)).fetchall()
    return [{**dict(r), 'page': spans[r['span_id']]['page'], 'quote': spans[r['span_id']]['text']} for r in rows if r['span_id'] in spans]


@router.put('/projects/{pid}/documents/{did}/annotations')
def save_annotation(pid: str, did: str, body: AnnotationBody):
    doc = document(pid, did)
    if body.span_id not in {s['id'] for s in json.loads(doc['spans'])}:
        raise HTTPException(422, '请选择这篇资料中存在的原文段落')
    with core.db() as conn:
        previous = conn.execute('SELECT 1 FROM annotations WHERE document_id=? AND span_id=?', (did, body.span_id)).fetchone()
        if not previous and conn.execute('SELECT COUNT(*) FROM annotations WHERE document_id=?', (did,)).fetchone()[0] >= 200:
            raise HTTPException(422, '单篇最多保存200段批注，可继续编辑已有笔记')
        conn.execute('INSERT INTO annotations VALUES (?,?,?,?,?) ON CONFLICT(document_id,span_id) DO UPDATE SET kind=excluded.kind,note=excluded.note,updated=excluded.updated',
                     (did, body.span_id, body.kind, body.note, datetime.now(timezone.utc).isoformat()))
    return next(a for a in annotations(pid, did) if a['span_id'] == body.span_id)


@router.get('/projects/{pid}/documents/{did}/notes.md')
def export_notes(pid: str, did: str):
    doc = document(pid, did)
    escape = lambda value: re.sub(r'([\\`*{}\[\]<>!#|_$])', r'\\\1', value)
    content = '# ' + escape(doc['title']).replace('\n', ' ') + ' 阅读笔记\n\n原文与个人批注分别保留，理解判断由作者核对。\n'
    kinds = {'highlight': '重点', 'confused': '待弄清', 'understood': '已理解'}
    items = annotations(pid, did)
    for item in items:
        content += f'\n## 第{item["page"]}页 · {item["span_id"]} · {kinds[item["kind"]]}\n\n'
        content += '\n'.join('> ' + escape(line) for line in item['quote'].splitlines())
        content += '\n\n个人批注：\n\n' + '\n'.join(escape(line) for line in item['note'].splitlines()) + '\n\n保存时间：' + item['updated'] + '\n'
    if not items:
        content += '\n尚未保存批注。\n'
    return Response(content, media_type='text/markdown; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="reading-notes.md"'})


@router.get('/projects/{pid}/reading-questions')
def reading_questions(pid: str, kind: Literal['confused', 'understood', 'all'] = 'confused', document_id: str = '', q: str = Query(default='', max_length=200), offset: int = Query(default=0, ge=0)):
    project(pid)
    if document_id:
        document(pid, document_id)
    clauses, params = ['d.project_id=?'], [pid]
    if document_id:
        clauses.append('a.document_id=?'); params.append(document_id)
    if kind != 'all':
        clauses.append('a.kind=?'); params.append(kind)
    if q.strip():
        clauses.append('(instr(lower(a.note),lower(?)) OR instr(lower(d.title),lower(?)))')
        params.extend([q.strip()] * 2)
    sql = ' FROM annotations a JOIN documents d ON d.id=a.document_id WHERE ' + ' AND '.join(clauses)
    with core.db() as conn:
        total = conn.execute('SELECT COUNT(*)' + sql, params).fetchone()[0]
        rows = conn.execute('SELECT a.*,d.title' + sql + ' ORDER BY a.updated DESC,a.document_id,a.span_id LIMIT 50 OFFSET ?', [*params, offset]).fetchall()
    items, pages = [], {}
    for row in rows:
        did = row['document_id']
        if did not in pages:
            spans = json.loads(document(pid, did)['spans'])
            counts = {}
            pages[did] = {}
            for span in spans:
                index = counts.get(span['page'], 0)
                pages[did][span['id']] = {**span, 'offset': index // 100 * 100}
                counts[span['page']] = index + 1
        span = pages[did].get(row['span_id'])
        if span:
            items.append({**dict(row), 'id': row['span_id'], 'quote': span['text'], 'page': span['page'], 'offset': span['offset']})
    return {'items': items, 'total': total, 'offset': offset, 'has_more': offset + len(rows) < total}


class AnnotationEdit(BaseModel):
    kind: Literal['highlight', 'confused', 'understood']
    note: str = Field(default='', max_length=4000)


@router.put('/projects/{pid}/reading-questions/{did}/{aid}')
def edit_question(pid: str, did: str, aid: str, body: AnnotationEdit):
    document(pid, did)
    with core.db() as conn:
        changed = conn.execute('UPDATE annotations SET kind=?,note=?,updated=? WHERE document_id=? AND span_id=?', (body.kind, body.note, datetime.now(timezone.utc).isoformat(), did, aid)).rowcount
        if not changed:
            raise HTTPException(404, '这条批注不存在')
    return next(a for a in annotations(pid, did) if a['span_id'] == aid)
