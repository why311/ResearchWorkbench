"""First literature stage: original files, page-aware text and project ownership."""
import io
import json
from pathlib import Path
import re
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfReader

from . import app as core

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT NOT NULL,filename TEXT NOT NULL,pages INTEGER NOT NULL,spans TEXT NOT NULL)')


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
