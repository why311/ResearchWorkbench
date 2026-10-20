"""Evidence-labelled paper reading, feedback and research handoff.

Reading questions are adapted from Wang-auspicious/paper-xray (MIT).
See THIRD_PARTY_NOTICES.md. This module never executes generated code.
"""
import html
import io
import json
from typing import Literal
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from . import app as core

router = APIRouter(prefix='/api')
SECTIONS = {'insight': '问题与洞见', 'mechanism': '机制与设定', 'math': '公式与手算',
            'experiments': '实验与证据', 'bench': '复现诊断', 'limits': '局限与下一步'}
GRADES = {'stated': '原文有据', 'inferred': '推断', 'speculative': '猜测', 'unreported': '本次材料未找到'}
KINDS = {'highlight': '重点', 'note': '笔记', 'confused': '不懂', 'verbose': '太长', 'understood': '已懂'}


def document(pid, did):
    core.project(pid)
    result = next((d for d in core.records('documents', pid) if d['id'] == did), None)
    if result is None:
        raise HTTPException(404, '当前项目没有这篇全文')
    return result


def get_record(pid, did):
    with core.db() as conn:
        row = conn.execute('SELECT * FROM paper_readings WHERE project_id=? AND document_id=?', (pid, did)).fetchone()
    return {**dict(row), 'entries': json.loads(row['entries']), 'coverage': json.loads(row['coverage'])} if row else None


class Entry(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,60}$')
    section: Literal['insight', 'mechanism', 'math', 'experiments', 'bench', 'limits']
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default='', max_length=8000)
    grade: Literal['stated', 'inferred', 'speculative', 'unreported'] = 'inferred'
    span_ids: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default='', max_length=2000)
    diagnostic: str = Field(default='', max_length=2000)
    cost: str = Field(default='', max_length=2000)
    note_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,60}$')


class ReadingBody(BaseModel):
    goal: Literal['concept', 'reproduce', 'math'] = 'reproduce'
    entries: list[Entry] = Field(default_factory=list, max_length=40)


def checked_entries(doc, entries):
    span_ids = {s['id'] for s in doc['spans']}
    if len({entry.id for entry in entries}) != len(entries):
        raise HTTPException(422, '精读条目的标识不能重复')
    for entry in entries:
        if not entry.title.strip():
            raise HTTPException(422, '请填写条目标题')
        if any(s not in span_ids for s in entry.span_ids):
            raise HTTPException(422, '条目引用包含不属于这篇全文的片段')
        if len(set(entry.span_ids)) != len(entry.span_ids):
            raise HTTPException(422, '同一条目不要重复引用同一片段')
        if entry.grade == 'stated' and not entry.span_ids:
            raise HTTPException(422, '原文有据的条目需关联至少一个原文片段；尚无依据时可标为推断或猜测')
        if entry.note_id:
            with core.db() as conn:
                linked = conn.execute('SELECT id FROM research_notes WHERE id=? AND project_id=?', (entry.note_id, doc['project_id'])).fetchone()
            if not linked:
                raise HTTPException(422, '关联的研究设想不属于当前项目或已不存在')
    return [entry.model_dump() for entry in entries]


def store_reading(pid, did, goal, entries, coverage=None, append=False):
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT * FROM paper_readings WHERE document_id=? AND project_id=?', (did, pid)).fetchone()
        if append:
            existing = json.loads(previous['entries']) if previous else []
            if len(existing) + len(entries) > 40:
                raise HTTPException(422, '精读条目累计超过40条，请先整理已有笔记后再生成')
            entries = existing + entries
        links = {e['id']: e.get('note_id') for e in json.loads(previous['entries'])} if previous else {}
        for entry in entries:
            if links.get(entry['id']):
                entry['note_id'] = links[entry['id']]
        actual_coverage = coverage if coverage is not None else json.loads(previous['coverage']) if previous else {'mode': 'manual'}
        conn.execute('INSERT INTO paper_readings VALUES (?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET goal=excluded.goal,entries=excluded.entries,coverage=excluded.coverage,updated=excluded.updated',
            (previous['id'] if previous else core.uid(), pid, did, goal, json.dumps(entries, ensure_ascii=False), json.dumps(actual_coverage, ensure_ascii=False), core.now()))


@router.get('/projects/{pid}/paper-readings/{did}')
def get_reading(pid: str, did: str):
    doc = document(pid, did)
    record = get_record(pid, did) or {'document_id': did, 'goal': 'reproduce', 'entries': [], 'coverage': {'mode': 'manual'}, 'updated': None}
    annotations = [a for a in core.records('reading_annotations', pid) if a['document_id'] == did]
    return {**record, 'title': doc['title'], 'pages': doc['pages'], 'annotations': annotations}


@router.put('/projects/{pid}/paper-readings/{did}')
def save_reading(pid: str, did: str, body: ReadingBody):
    doc = document(pid, did)
    entries = checked_entries(doc, body.entries)
    store_reading(pid, did, body.goal, entries)
    return get_reading(pid, did)


class GenerateBody(BaseModel):
    goal: Literal['concept', 'reproduce', 'math'] = 'reproduce'
    start_page: int = Field(default=1, ge=1, le=300)
    end_page: int = Field(ge=1, le=300)


@router.post('/projects/{pid}/paper-readings/{did}/generate')
def generate_reading(pid: str, did: str, body: GenerateBody):
    doc = document(pid, did)
    remaining = 40 - len((get_record(pid, did) or {}).get('entries', []))
    if remaining <= 0:
        raise HTTPException(422, '已有40条精读笔记，请先整理后再生成')
    limit = min(18, remaining)
    if not body.start_page <= body.end_page <= doc['pages']:
        raise HTTPException(422, '请选择有效的原文页范围')
    spans = [s for s in doc['spans'] if body.start_page <= s['page'] <= body.end_page]
    if not spans:
        raise HTTPException(422, '选定页范围未提取到文字，请检查原PDF或进行OCR')
    material = '\n\n'.join(f"[{s['id']}|第{s['page']}页]\n{s['text']}" for s in spans)
    if len(material) > 60000:
        raise HTTPException(422, '选定范围的文字超过60000字符，请缩小页范围。系统不会静默截断后冒充读完全文。')
    annotations = get_reading(pid, did)['annotations']
    feedback = [{'quote': a['quote'], 'kind': KINDS[a['kind']], 'note': a['note']} for a in annotations if a['span_id'] in {s['id'] for s in spans}]
    # Bound the supplementary feedback independently; original passages stay intact.
    feedback_text = json.dumps(feedback, ensure_ascii=False)
    if len(feedback_text) > 20000:
        raise HTTPException(422, '本次范围的批注较多，请缩小页范围后生成，避免遗漏阅读反馈')
    instruction = '''生成可编辑的中文论文精读草稿，不复述摘要。只使用本次页范围的提取文字。
正文、附录、图注、表注均须按实际提供的材料判断；你看不到未提供的图像、公式原图、代码或外部文献。
逐项区分：stated原文有据、inferred推断、speculative猜测、unreported本次材料未找到。作者意图不能冒充事实。
每条stated必须附真实span_ids及quotes，quotes逐字摘录对应原文；引用定位只验证来源存在，不证明解释正确。
从问题/失败场景出发解释关键机制。复现诊断给出可能症状、最小诊断和补丁代价，未运行的诊断不能声称已验证。
公式条目先交代符号含义/形状/假设，再说明运算及手算步骤；示意数字须标注示意，不代替论文结果。
核对实验是否控制变量、差异与波动、缺失的种子/计算预算/对照；在材料里没找到不等于整篇论文没有报告。
只有explicit已懂反馈才略讲对应内容；不懂反馈换角度展开，划重点不视为已懂，太长反馈缩短相应部分。
输出JSON {"entries":[{"section":"insight|mechanism|math|experiments|bench|limits","title":"具体短标题","body":"解释，可用$LaTeX$或$$LaTeX$$","grade":"stated|inferred|speculative|unreported","span_ids":["p1-s1"],"quotes":["对应原文"],"rationale":"推断依据或待核对说明","diagnostic":"最低成本诊断，适用于bench","cost":"补丁代价，适用于bench"}]}，最多18条。不要生成HTML或可执行代码。'''
    instruction = instruction.replace('最多18条', f'最多{limit}条')
    instruction += '\n阅读目标：' + {'concept': '先讲直觉、必要背景和小例子。', 'reproduce': '关注具体设定、失败症状、诊断顺序和代价。', 'math': '关注符号形状、假设、关键推导和可核对的小例子。'}[body.goal]
    output = core.model_json(instruction, material + '\n\n读者明确反馈：\n' + feedback_text)
    if output is None:
        raise HTTPException(409, '尚未配置模型。你仍可阅读原文、记录批注并手动建立精读条目；配置模型后可生成草稿。')
    if not isinstance(output.get('entries'), list):
        raise HTTPException(502, '模型没有返回精读条目，请重试或手动记录')
    known = {s['id']: s for s in spans}
    entries, warnings = [], []
    for raw in output['entries'][:limit]:
        if not isinstance(raw, dict):
            warnings.append('忽略了格式无效的模型条目')
            continue
        candidate = {**raw, 'id': core.uid(), 'note_id': None}
        try:
            entry = Entry.model_validate(candidate)
        except ValidationError:
            warnings.append('忽略了字段不符合要求的模型条目')
            continue
        if not entry.title.strip():
            warnings.append('忽略了标题为空的模型条目')
            continue
        valid = list(dict.fromkeys(s for s in entry.span_ids if s in known))
        quotes = raw.get('quotes')
        quote_verified = isinstance(quotes, list) and len(quotes) == len(entry.span_ids) and len(valid) == len(entry.span_ids) and all(isinstance(q, str) and q.strip() and q in known[s]['text'] for s, q in zip(entry.span_ids, quotes))
        if entry.grade == 'stated' and (not valid or not quote_verified):
            entry.grade = 'speculative'
            entry.rationale = '模型未提供可逐字核对的原文引文，该条暂列猜测，需人工核对。' + entry.rationale[:1600]
            warnings.append('有原文引文未通过核对，已降为猜测')
        entry.span_ids = valid
        entries.append(entry.model_dump())
    if not entries:
        raise HTTPException(502, '没有得到有效精读条目，请重试或手动记录')
    document(pid, did)
    coverage = {'mode': 'model', 'start_page': body.start_page, 'end_page': body.end_page, 'spans': len(spans), 'characters': len(material), 'feedback_count': len(feedback)}
    store_reading(pid, did, body.goal, entries, coverage, append=True)
    return {**get_reading(pid, did), 'warnings': list(dict.fromkeys(warnings)), 'saved': True}


class AnnotationBody(BaseModel):
    span_id: str
    quote: str = Field(min_length=1, max_length=1600)
    kind: Literal['highlight', 'note', 'confused', 'verbose', 'understood'] = 'note'
    note: str = Field(default='', max_length=2000)


@router.post('/projects/{pid}/paper-readings/{did}/annotations')
def add_annotation(pid: str, did: str, body: AnnotationBody):
    doc = document(pid, did)
    span = next((s for s in doc['spans'] if s['id'] == body.span_id), None)
    if not span or not body.quote.strip() or body.quote not in span['text']:
        raise HTTPException(422, '批注引文需来自所选原文片段，不能引用其他文献或改写后的文字')
    aid, created = core.uid(), core.now()
    with core.db() as conn:
        if conn.execute('SELECT COUNT(*) FROM reading_annotations WHERE document_id=?', (did,)).fetchone()[0] >= 200:
            raise HTTPException(422, '单篇文献最多保存200条批注')
        conn.execute('INSERT INTO reading_annotations VALUES (?,?,?,?,?,?,?,?,?)', (aid, pid, did, body.span_id, body.quote, body.kind, body.note, created, created))
    return get_reading(pid, did)


@router.delete('/projects/{pid}/paper-readings/{did}/annotations/{aid}')
def remove_annotation(pid: str, did: str, aid: str):
    document(pid, did)
    with core.db() as conn:
        row = conn.execute('SELECT * FROM reading_annotations WHERE id=? AND document_id=? AND project_id=?', (aid, did, pid)).fetchone()
        if not row:
            raise HTTPException(404, '批注不存在')
        conn.execute('DELETE FROM reading_annotations WHERE id=?', (aid,))
    return dict(row)


@router.post('/projects/{pid}/paper-readings/{did}/entries/{eid}/research-note')
def promote_entry(pid: str, did: str, eid: str):
    doc = document(pid, did)
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM paper_readings WHERE project_id=? AND document_id=?', (pid, did)).fetchone()
        entries = json.loads(row['entries']) if row else []
        entry = next((e for e in entries if e['id'] == eid), None)
        if not entry:
            raise HTTPException(404, '请先保存这条精读笔记')
        if entry.get('note_id'):
            return {'id': entry['note_id'], 'created': False}
        nid, created = core.uid(), core.now()
        prediction = entry['diagnostic'] or '待作者补充：改变什么因素、观察什么量，以及什么结果会推翻这条设想。'
        hypothesis = entry['body'] + '\n\n原精读证据等级：' + GRADES[entry['grade']]
        refs = [{'document_id': did, 'span_id': s} for s in entry['span_ids']]
        conn.execute('INSERT INTO research_notes VALUES (?,?,?,?,?,?,?,?,?,?,?)', (nid, pid, entry['title'], hypothesis[:4000], prediction[:4000], 'planned', '来自精读笔记，尚未执行验证。' + ('\n预期代价：' + entry['cost'] if entry['cost'] else ''), json.dumps(refs), '[]', created, created))
        entry['note_id'] = nid
        conn.execute('UPDATE paper_readings SET entries=?,updated=? WHERE document_id=?', (json.dumps(entries, ensure_ascii=False), created, did))
    return {'id': nid, 'created': True}


@router.get('/projects/{pid}/paper-readings/{did}/export')
def export_reading(pid: str, did: str):
    doc = document(pid, did)
    reading = get_reading(pid, did)
    text = f"# {doc['title']} · 精读笔记\n\n"
    text += '以下为作者保存的阅读笔记；来源定位不等于解释正确。未执行的诊断、示意推导不作为实验结果。\n\n'
    text += '读取范围：' + json.dumps(reading['coverage'], ensure_ascii=False) + '\n\n'
    spans = {s['id']: s for s in doc['spans']}
    used = set()
    for section, label in SECTIONS.items():
        entries = [e for e in reading['entries'] if e['section'] == section]
        if not entries:
            continue
        text += f'## {label}\n\n'
        for entry in entries:
            text += f"### {entry['title']}\n\n证据等级：{GRADES[entry['grade']]}\n\n{entry['body']}\n\n"
            for key, title in [('rationale', '判断依据'), ('diagnostic', '最低成本诊断'), ('cost', '补丁与代价')]:
                if entry.get(key):
                    text += f"{title}：{entry[key]}\n\n"
            for sid in entry['span_ids']:
                used.add(sid)
                text += f"来源：第{spans[sid]['page']}页 · {sid}\n\n> " + spans[sid]['text'].replace('\n', '\n> ') + '\n\n'
    text += '## 阅读批注\n\n'
    for a in reading['annotations']:
        used.add(a['span_id'])
        text += f"- {KINDS[a['kind']]} · 第{spans[a['span_id']]['page']}页 · {a['span_id']}\n\n> {a['quote']}\n\n{a['note']}\n\n"
    offline = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(doc['title']) + '</title><style>body{margin:0;background:#f7f9fc;color:#182338;font:16px/1.9 "Microsoft YaHei",sans-serif}main{max-width:900px;margin:auto;padding:40px 24px}pre{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}</style><main><h1>' + html.escape(doc['title']) + '</h1><p>离线只读副本，批注已包含在文中；公式保留源文本。</p><pre>' + html.escape(text) + '</pre></main></html>'
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('reading.md', text)
        archive.writestr('reading.html', offline)
        archive.writestr('sources.json', json.dumps({**reading, 'source_spans': [spans[s] for s in spans if s in used]}, ensure_ascii=False, indent=2))
    return Response(memory.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="paper-reading.zip"'})
