"""Non-destructive revisions, numbered citation navigation and reading aids."""
import difflib
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app as core
from .documents import document, spans

router = APIRouter(prefix='/api')
with core.db() as conn:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS document_versions(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,preferred_id TEXT REFERENCES documents(id) ON DELETE SET NULL,updated TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS document_metadata(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,metadata TEXT NOT NULL,updated TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS page_interpretations(document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,page INTEGER NOT NULL,result TEXT NOT NULL,updated TEXT NOT NULL,PRIMARY KEY(document_id,page));
    ''')


class RevisionBody(BaseModel):
    previous_id: str
    current_id: str
    mode: Literal['coexist', 'prefer'] = 'coexist'


@router.post('/projects/{pid}/document-versions')
def version_choice(pid: str, body: RevisionBody):
    for did in (body.previous_id, body.current_id):
        doc = document(pid, did)
        with core.db() as conn:
            task = conn.execute('SELECT status FROM document_ingestions WHERE document_id=?', (did,)).fetchone()
        if task and task['status'] != 'completed':
            raise HTTPException(409, '请等待两份文献解析完成后整理版本')
    if body.previous_id == body.current_id:
        raise HTTPException(422, '请选择两份不同的文献')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if body.mode == 'prefer':
            linked = conn.execute('SELECT preferred_id FROM document_versions WHERE document_id=?', (body.current_id,)).fetchone()
            if linked and linked['preferred_id']:
                raise HTTPException(409, '新版本当前仍指向另一份优先版本，请先恢复并存，避免循环版本关系')
        conn.execute('INSERT INTO document_versions VALUES (?,?,?) ON CONFLICT(document_id) DO UPDATE SET preferred_id=excluded.preferred_id,updated=excluded.updated',
                     (body.previous_id, body.current_id if body.mode == 'prefer' else None, core.now()))
    return {'saved': True, 'message': '版本已整理，旧原件、批注和历史引用保持可追溯。'}


@router.get('/projects/{pid}/document-versions')
def versions(pid: str):
    core.project(pid)
    with core.db() as conn:
        return [dict(r) for r in conn.execute('SELECT v.* FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.project_id=?', (pid,))]


@router.get('/projects/{pid}/document-diff')
def diff(pid: str, previous_id: str, current_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200)):
    before, after = document(pid, previous_id), document(pid, current_id)
    a, b = list(spans(before)), list(spans(after))
    if len(a) + len(b) > 30000:
        raise HTTPException(422, '两份资料合计超过30000段，请按章节拆分后比较')
    operations = difflib.SequenceMatcher(None, [s['text'] for s in a], [s['text'] for s in b], autojunk=True).get_opcodes()
    changes = [{'kind': tag, 'before': a[i:j], 'after': b[k:l]} for tag, i, j, k, l in operations if tag != 'equal']
    return {'previous': {'id': before['id'], 'title': before['title']}, 'current': {'id': after['id'], 'title': after['title']},
            'total': len(changes), 'offset': offset, 'items': changes[offset:offset + limit], 'has_more': offset + limit < len(changes),
            'summary': {tag: sum((j-i if tag == 'delete' else l-k) for t, i, j, k, l in operations if t == tag) for tag in ('insert', 'delete', 'replace')},
            'scope': '按已解析段落逐字比较，页码与片段随变更保留；解析与OCR差异也可能产生变更，不等于科学结论变化。'}


@router.get('/projects/{pid}/document-diff/export')
def diff_export(pid: str, previous_id: str, current_id: str):
    data = diff(pid, previous_id, current_id, 0, 200)
    while data['has_more']:
        following = diff(pid, previous_id, current_id, len(data['items']), 200)
        data['items'].extend(following['items']); data['has_more'] = following['has_more']
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="document-diff.json"'})


NUMBER = re.compile(r'\[(\d{1,4})(?:\s*[,，;；–—-]\s*\d{1,4})*\]')


@router.get('/projects/{pid}/documents/{did}/citation-map')
def citation_map(pid: str, did: str):
    doc = document(pid, did)
    blocks = list(spans(doc))
    reference_heading = re.compile(r'\s*(?:\d+\.?\s*)?(?:references|bibliography|参考文献)\s*', re.I)
    has_heading = any(reference_heading.fullmatch(s['text']) for s in blocks)
    numbered_pages = set()
    for span in blocks:
        if span.get('kind') == 'heading' and re.match(r'^\s*(?:appendix\b|附录)', span['text'], re.I):
            break
        if re.search(r'(?:^|\n)\s*\[\d{1,4}\]\s*\S', span['text']):
            numbered_pages.add(span['page'])
    refs, mentions, active, last_number, closed = {}, [], False, None, False
    for span in blocks:
        if reference_heading.fullmatch(span['text']):
            active = True
            closed = False
            continue
        if active and re.match(r'^\s*(?:appendix|附录)\b', span['text'], re.I):
            active = False
            closed = True
        entries = list(re.finditer(r'(?:^|\n)\s*\[(\d{1,4})\]\s*(?=\S)', span['text']))
        if active and last_number and span['page'] > refs[last_number]['page'] and span['page'] not in numbered_pages:
            active, closed = False, True
        if active and not entries and span.get('kind') == 'heading' and len(span['text'].strip()) > 3 and span['text'].strip() != doc['title'].strip():
            active, closed = False, True
        if entries and (active or not has_heading and not closed and span['page'] >= max(1, doc['pages'] * .6)):
            for index, entry in enumerate(entries):
                number = int(entry[1])
                end = entries[index+1].start() if index+1 < len(entries) else len(span['text'])
                refs.setdefault(number, {'number': number, 'span_id': span['id'], 'page': span['page'], 'text': span['text'][entry.start():end].strip(), 'backlinks': []})
                last_number = number
            active = True
            continue
        if active and last_number and span.get('kind') != 'heading':
            refs[last_number]['text'] += '\n' + span['text']
        if not active:
            for match in NUMBER.finditer(span['text']):
                nums = re.findall(r'\d+', match[0])
                if re.search('[–—-]', match[0]) and len(nums) == 2:
                    nums = range(int(nums[0]), min(int(nums[1]), int(nums[0]) + 100) + 1)
                for number in dict.fromkeys(map(int, nums)):
                    mentions.append({'number': number, 'span_id': span['id'], 'page': span['page'], 'text': span['text'], 'start': match.start(), 'end': match.end()})
    for mention in mentions:
        if mention['number'] in refs:
            refs[mention['number']]['backlinks'].append(mention)
    return {'references': list(refs.values()), 'mentions': [m for m in mentions if m['number'] in refs],
            'unmatched': [m for m in mentions if m['number'] not in refs], 'scope': '识别方括号编号与参考文献条目；解析合并、作者年份制和OCR错误需人工核对。'}


class SelectionBody(BaseModel):
    span_id: str
    selection: str = Field(min_length=1, max_length=3000)
    language: Literal['zh', 'en'] = 'zh'


@router.post('/projects/{pid}/documents/{did}/translate-selection')
def translate_selection(pid: str, did: str, body: SelectionBody):
    from .literature import passage
    span = passage(pid, did, body.span_id)
    if body.selection not in span['text']:
        raise HTTPException(422, '选中文字与该段原文不一致，请重新选择')
    result = core.model_json('仅翻译selection为' + ('中文' if body.language == 'zh' else '英文') + '，参考context保持学术术语、公式、数字和不确定性。返回JSON {"translation":"译文"}。', json.dumps({'selection': body.selection, 'context': span['text']}, ensure_ascii=False))
    if not result:
        raise HTTPException(409, '请先配置模型服务')
    text = result.get('translation')
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise HTTPException(502, '模型没有返回有效译文')
    return {'translation': text, 'source': body.selection, 'span_id': body.span_id, 'page': span['page'], 'method': 'model', 'reviewed': False}


class MetadataBody(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=100)
    year: str = Field(default='', max_length=4, pattern=r'^\d{4}$|^$')
    venue: str = Field(default='', max_length=500)
    doi: str = Field(default='', max_length=300)
    url: str = Field(default='', max_length=2000)
    kind: Literal['J', 'C', 'M', 'D', 'EB/OL'] = 'J'
    volume: str = Field(default='', max_length=50)
    issue: str = Field(default='', max_length=50)
    pages: str = Field(default='', max_length=100)
    publisher: str = Field(default='', max_length=300)


@router.get('/projects/{pid}/documents/{did}/metadata')
def metadata(pid: str, did: str):
    doc = document(pid, did)
    with core.db() as conn:
        saved = conn.execute('SELECT metadata FROM document_metadata WHERE document_id=?', (did,)).fetchone()
        task = conn.execute('SELECT profile FROM document_ingestions WHERE document_id=?', (did,)).fetchone()
    profile = json.loads(task['profile']) if task else {}
    original = profile.get('metadata_source', {})
    return {**{'volume':'','issue':'','pages':'','publisher':''}, **(json.loads(saved['metadata']) if saved else {'title': doc['title'], 'authors': original.get('authors', []), 'year': original.get('published', '')[:4], 'venue': '', 'doi': profile.get('doi', ''), 'url': original.get('url', ''), 'kind': 'J'})}


@router.put('/projects/{pid}/documents/{did}/metadata')
def save_metadata(pid: str, did: str, body: MetadataBody):
    document(pid, did)
    if not body.title.strip() or any(len(a) > 200 or not a.strip() for a in body.authors):
        raise HTTPException(422, '题名及作者信息无效')
    if body.url and not re.match(r'^https?://[^\s]+$', body.url):
        raise HTTPException(422, '文献地址须为HTTP或HTTPS网址')
    with core.db() as conn:
        conn.execute('INSERT INTO document_metadata VALUES (?,?,?) ON CONFLICT(document_id) DO UPDATE SET metadata=excluded.metadata,updated=excluded.updated', (did, body.model_dump_json(), core.now()))
    return body.model_dump()


@router.get('/projects/{pid}/bibliography')
def bibliography(pid: str, style: Literal['gbt', 'apa', 'bibtex'] = 'gbt'):
    core.project(pid)
    with core.db() as conn:
        ids = [r[0] for r in conn.execute('SELECT id FROM documents WHERE project_id=? ORDER BY created,id', (pid,))]
    lines, missing = [], []
    for index, did in enumerate(ids, 1):
        m = metadata(pid, did)
        absent = [k for k in ('authors', 'year', 'venue') if not m[k]]
        if absent:
            missing.append({'document_id': did, 'fields': absent})
        authors, year, venue = ', '.join(m['authors']) or '[作者待补]', m['year'] or '[年份待补]', m['venue'] or '[出版物待补]'
        if style == 'gbt':
            detail = (', ' + m['volume'] if m['volume'] else '') + ('(' + m['issue'] + ')' if m['issue'] else '') + (': ' + m['pages'] if m['pages'] else '')
            line = f'[{index}] {authors}. {m["title"]}[{m["kind"]}]. {venue}, {year}{detail}.'
        elif style == 'apa':
            detail = (', ' + m['volume'] if m['volume'] else '') + ('(' + m['issue'] + ')' if m['issue'] else '') + (', ' + m['pages'] if m['pages'] else '')
            line = f'{authors} ({year}). {m["title"]}. {venue}{detail}.'
        else:
            escape = lambda s: str(s).replace('\\', '\\textbackslash{}').replace('{', '\\{').replace('}', '\\}').replace('\n', ' ')
            line = '@misc{paper' + str(index) + ',\n' + ',\n'.join('  ' + k + ' = {' + escape(v) + '}' for k, v in {'title': m['title'], 'author': ' and '.join(m['authors']), 'year': m['year'], 'howpublished': m['venue'], 'doi': m['doi'], 'url': m['url']}.items() if v) + '\n}'
        if style != 'bibtex' and (m['doi'] or m['url']):
            line += ' ' + ('https://doi.org/' + m['doi'] if m['doi'] else m['url'])
        lines.append(line)
    return {'text': '\n\n'.join(lines), 'missing': missing, 'scope': '依据已核对题录排版；缺失信息显式留空待补。GB/T和APA为基础字段样式，不推断未知卷期页码。'}
