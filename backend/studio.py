"""Dataset import, cleaning and reproducible descriptive analysis."""
import csv
import io
import json
import math
from pathlib import Path
import re
import threading
from typing import Literal
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from openpyxl import load_workbook
from pydantic import BaseModel, Field, model_validator

from . import app as core
from .experiments import regular_file
from .analysis_runner import MISSING, number, write_csv, configure_plot
from .report_text import CITATION, body_markdown, evidence_markdown

router = APIRouter(prefix='/api')


def dataset(pid, did):
    core.project(pid)
    result = next((d for d in core.records('datasets', pid) if d['id'] == did), None)
    if result is None:
        raise HTTPException(404, '数据集不存在')
    return result


def parse_table(filename, content):
    suffix = Path(filename).suffix.lower()
    metadata = {}
    if suffix == '.xlsx':
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zipped:
                if sum(f.file_size for f in zipped.infolist()) > 50 * 1024 * 1024:
                    raise HTTPException(413, 'Excel解压后超过50MB，请只导出必要数据表')
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
            try:
                sheet = book.worksheets[0]
                metadata = {'sheet': sheet.title, 'sheet_count': len(book.worksheets), 'encoding': 'XLSX'}
                values = []
                for i, cells in enumerate(sheet.iter_rows()):
                    if i > 100000 or len(cells) > 100:
                        raise HTTPException(413, '数据表最大100000行、100列')
                    if any(c.data_type == 'f' for c in cells):
                        raise HTTPException(422, 'Excel包含公式，请先将公式转为数值后上传，避免使用未计算的值')
                    values.append(['' if c.value is None else str(c.value) for c in cells])
            finally:
                book.close()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, '无法读取Excel，请检查文件或导出为CSV')
    elif suffix in {'.csv', '.tsv'}:
        try:
            text = content.decode('utf-8-sig')
            metadata['encoding'] = 'UTF-8'
        except UnicodeDecodeError:
            try:
                text = content.decode('gb18030')
                metadata['encoding'] = 'GB18030'
            except UnicodeDecodeError:
                raise HTTPException(422, '无法识别文字编码，请导出UTF-8数据')
        try:
            values = []
            for i, row in enumerate(csv.reader(io.StringIO(text), delimiter='\t' if suffix == '.tsv' else ',', strict=True)):
                if i > 100000 or len(row) > 100:
                    raise HTTPException(413, '数据表最大100000行、100列')
                values.append(row)
        except csv.Error:
            raise HTTPException(422, '表格分隔或引号格式无效')
    else:
        raise HTTPException(422, '支持CSV、TSV和XLSX数据表')
    values = [r for r in values if any(str(v).strip() for v in r)]
    if len(values) < 2:
        raise HTTPException(422, '数据表至少需要一行字段名和一行数据')
    headers = [v.strip() for v in values[0]]
    if not all(headers) or len(set(headers)) != len(headers) or any(len(h) > 128 for h in headers):
        raise HTTPException(422, '字段名须非空、不重复且不超过128字')
    if len(headers) > 100 or len(values) > 100001:
        raise HTTPException(413, '数据表最大100000行、100列')
    rows = []
    for i, row in enumerate(values[1:], 2):
        if len(row) != len(headers):
            raise HTTPException(422, f'第{i}行的字段数量与表头不同')
        rows.append([str(v).strip() for v in row])
    return headers, rows, metadata


def add_dataset(pid, filename, headers, rows, metadata):
    did = core.uid()
    profile = {**metadata, 'duplicates': len(rows) - len(set(tuple(r) for r in rows)), 'fields': [], 'preview': [[v[:200] for v in r] for r in rows[:15]]}
    for i, column in enumerate(headers):
        values = [r[i] for r in rows]
        missing = sum(v.lower() in MISSING for v in values)
        numeric = [number(v) for v in values if number(v) is not None]
        count = len(numeric)
        profile['fields'].append({'name': column, 'missing': missing, 'numeric_count': count, 'unique_count': len(set(values)),
            'invalid_numeric': len(rows) - missing - count, 'kind': 'numeric' if count and count + missing == len(rows) else 'mixed' if count else 'text',
            'min': min(numeric) if numeric else None, 'max': max(numeric) if numeric else None,
            'examples': [v[:120] for v in list(dict.fromkeys(values))[:4]]})
    folder = core.DATA / 'datasets' / did
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'input.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)
    with core.db() as conn:
        conn.execute('INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?)',
                     (did, pid, Path(filename).stem, filename, len(rows), json.dumps(headers), json.dumps(profile, ensure_ascii=False), core.now()))
    return dataset(pid, did)


@router.post('/projects/{pid}/datasets')
async def upload_dataset(pid: str, file: UploadFile = File(...)):
    core.project(pid)
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, '数据文件最大10MB')
    filename = Path(file.filename or 'data.csv').name
    headers, rows, metadata = parse_table(filename, content)
    return add_dataset(pid, filename, headers, rows, metadata)


@router.post('/projects/{pid}/datasets/demo')
def demo_dataset(pid: str):
    core.project(pid)
    existing = next((d for d in core.records('datasets', pid) if d['profile'].get('source') == 'demo'), None)
    if existing:
        return existing
    return add_dataset(pid, '示例测量数据.csv', ['group', 'score', 'time_ms'],
        [['A', '70', '100'], ['A', '80', '120'], ['A', '', '140'], ['B', '85', '90'], ['B', '95', '110'], ['B', '95', '110']],
        {'source': 'demo', 'encoding': 'UTF-8', 'description': '人工编写的流程示例，包含缺失值和重复行，不是实际研究数据。'})


class ImportArtifact(BaseModel):
    run_id: str
    filename: str


@router.post('/projects/{pid}/datasets/from-run')
def import_run_dataset(pid: str, body: ImportArtifact):
    run = core.run_record(pid, body.run_id)
    if body.filename not in run['artifacts'] or Path(body.filename).name != body.filename or Path(body.filename).suffix.lower() not in {'.csv', '.tsv'}:
        raise HTTPException(422, '请选择本项目运行产生的CSV或TSV文件')
    path = core.DATA / 'runs' / run['id'] / body.filename
    if not regular_file(path):
        raise HTTPException(404, '结果表不存在')
    if path.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(413, '结果表超过10MB')
    headers, rows, metadata = parse_table(body.filename, path.read_bytes())
    return add_dataset(pid, body.filename, headers, rows, {**metadata, 'source_run_id': run['id'], 'source_run_name': run['name']})


class RangeFilter(BaseModel):
    column: str
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode='after')
    def bounds(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('筛选下限不能大于上限')
        return self


class AnalysisPlan(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=12)
    missing: Literal['keep', 'drop', 'median'] = 'keep'
    deduplicate: bool = False
    scales: dict[str, float] = Field(default_factory=dict)
    filters: list[RangeFilter] = Field(default_factory=list, max_length=12)
    methods: list[Literal['summary', 'groups', 'correlation', 'line', 'radar', 'radar3d']] = Field(default=['summary'], min_length=1, max_length=6)
    group_by: str = ''
    x_column: str = ''


class AnalysisBody(BaseModel):
    name: str = Field(default='数据分析', min_length=1, max_length=100)
    dataset_id: str
    plan: AnalysisPlan
    timeout: int = Field(default=120, ge=10, le=1800)


@router.post('/projects/{pid}/analysis')
def start_analysis(pid: str, body: AnalysisBody):
    d = dataset(pid, body.dataset_id)
    plan = body.plan.model_dump()
    if len(set(plan['columns'])) != len(plan['columns']) or any(c not in d['columns'] for c in plan['columns']):
        raise HTTPException(422, '分析字段重复或不存在')
    if plan['group_by'] and (plan['group_by'] not in d['columns'] or plan['group_by'] in plan['columns']):
        raise HTTPException(422, '分组字段应与数值分析字段不同，且须存在')
    if 'groups' in plan['methods'] and not plan['group_by']:
        raise HTTPException(422, '分组比较需要选择分组字段')
    if 'groups' in plan['methods'] and next(f for f in d['profile']['fields'] if f['name'] == plan['group_by'])['unique_count'] > 200:
        raise HTTPException(422, '分组字段超过200种取值，请选择分类字段或先整理分组')
    if 'correlation' in plan['methods'] and len(plan['columns']) < 2:
        raise HTTPException(422, '相关分析至少需要两个数值字段')
    if any(m in plan['methods'] for m in ('radar', 'radar3d')) and len(plan['columns']) < 3:
        raise HTTPException(422, '雷达图至少需要三个数值字段')
    if plan['x_column'] and plan['x_column'] not in plan['columns']:
        raise HTTPException(422, '折线图横轴须为已选数值字段')
    if any(c not in plan['columns'] or not math.isfinite(v) for c, v in plan['scales'].items()):
        raise HTTPException(422, '换算系数须为有限数值，并对应所选字段')
    if any(f['column'] not in plan['columns'] for f in plan['filters']):
        raise HTTPException(422, '筛选字段必须包含在数值分析字段中')
    rid = core.uid()
    config = {'recipe': 'analysis', 'dataset_id': d['id'], 'dataset_name': d['name'], 'plan': plan, 'timeout': body.timeout}
    with core.db() as conn:
        conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)', (rid, pid, body.name, 'queued', json.dumps(config, ensure_ascii=False), '{}', '', '[]', core.now(), None))
    threading.Thread(target=core.execute_run, args=(pid, rid, config), daemon=True).start()
    return core.run_record(pid, rid)


@router.get('/projects/{pid}/analysis/{rid}')
def analysis_result(pid: str, rid: str):
    run = core.run_record(pid, rid)
    if run['config']['recipe'] != 'analysis':
        raise HTTPException(422, '此记录不是数据分析')
    path = core.DATA / 'runs' / rid / 'analysis.json'
    return {'run': core.get_run(pid, rid), 'result': json.loads(path.read_text(encoding='utf-8')) if run['status'] == 'succeeded' and path.exists() else None}


@router.get('/projects/{pid}/analysis/{rid}/export')
def export_analysis(pid: str, rid: str):
    run = core.run_record(pid, rid)
    if run['config']['recipe'] != 'analysis' or run['status'] != 'succeeded':
        raise HTTPException(409, '成功完成分析后才能导出复跑包')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in (core.DATA / 'runs' / rid).iterdir():
            if path.is_file():
                archive.write(path, path.name)
        archive.writestr('requirements.txt', 'numpy\nmatplotlib\n')
        archive.writestr('README.md', '# 可复跑分析\n\n环境版本记录在environment.json。\n\n复跑：\n```\npython analysis_runner.py --input input.csv --plan config.json --output rerun\n```\n\n处理计划、原始数据、处理计数和实际结果均随包保存。分析结果不自动支持因果或显著性结论。\n')
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="analysis-replay.zip"'})


PLOT_LOCK = threading.Lock()


class Binding(BaseModel):
    alias: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,39}$')
    run_id: str
    metric: str
    precision: int = Field(default=4, ge=0, le=8)
    display: Literal['number', 'percent'] = 'number'


class Citation(BaseModel):
    alias: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,39}$')
    document_id: str
    span_id: str


class ReportBody(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    template: str = Field(default='', max_length=30000)
    bindings: list[Binding] = Field(default_factory=list, max_length=30)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    chart_run_ids: list[str] = Field(default_factory=list, max_length=20)
    chart_metrics: list[str] = Field(default_factory=list, max_length=6)


@router.get('/projects/{pid}/reports')
def list_reports(pid: str):
    core.project(pid)
    with core.db() as conn:
        return [dict(row) for row in conn.execute(
            'SELECT id,title FROM reports WHERE project_id=? ORDER BY updated DESC,rowid DESC', (pid,))]


class DraftSource(BaseModel):
    draft_id: str


@router.post('/projects/{pid}/reports/from-draft')
def report_from_draft(pid: str, body: DraftSource):
    from .writing_drafts import get_draft

    draft = get_draft(pid, body.draft_id)
    if len(draft['template']) > 30000:
        raise HTTPException(422, '请将草稿正文缩短至 30000 字符以内再转为成果文稿')
    return create_report(pid, ReportBody(title=draft['title'], template=draft['template'], citations=draft['citations']))


def report_record(pid, report_id):
    core.project(pid)
    record = next((r for r in core.records('reports', pid) if r['id'] == report_id), None)
    if record is None:
        raise HTTPException(404, '成果文稿不存在')
    return record


def resolve_report(record):
    runs = {r['id']: r for r in core.records('runs', record['project_id'])}
    resolved, errors = [], []
    for binding in record['bindings']:
        run = runs.get(binding['run_id'])
        value = run['metrics'].get(binding['metric']) if run and run['status'] == 'succeeded' else None
        if type(value) not in (int, float) or not math.isfinite(value):
            errors.append(f'变量 {binding["alias"]} 的来源结果不存在或未成功完成')
            continue
        if binding['display'] == 'percent' and not math.isfinite(value * 100):
            errors.append(f'变量 {binding["alias"]} 转为百分比后溢出，请使用数值显示')
            continue
        formatted = f'{value * 100:.{binding["precision"]}f}%' if binding['display'] == 'percent' else f'{value:.{binding["precision"]}f}'
        resolved.append({**binding, 'value': value, 'formatted': formatted, 'run_name': run['name'], 'source_config': run['config'], 'source_created': run['created']})
    aliases = {r['alias']: r['formatted'] for r in resolved}
    referenced = set(re.findall(r'\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}', record['template']))
    errors.extend(f'文稿中的变量 {a} 尚未绑定有效结果' for a in sorted(referenced - aliases.keys()))
    citations, citation_errors = resolve_citations(record['project_id'], record['citations'])
    errors.extend(citation_errors)
    citation_map = {c['alias']: c for c in citations}
    used = list(dict.fromkeys(re.findall(CITATION, record['template'])))
    errors.extend(f'文稿中的文献引用 {a} 尚未绑定有效原文' for a in used if a not in citation_map)
    citations = [{**citation_map[a], 'number': i + 1} for i, a in enumerate(used) if a in citation_map]
    chart = []
    for rid in record['chart_run_ids']:
        run = runs.get(rid)
        if not run or run['status'] != 'succeeded':
            errors.append('图表来源包含不存在或尚未成功的运行')
            continue
        chart.append({'id': rid, 'name': run['name'], 'config': run['config'], 'created': run['created'], 'metrics': {m: run['metrics'].get(m) for m in record['chart_metrics']}})
    for metric in record['chart_metrics']:
        if not any(type(r['metrics'].get(metric)) in (int, float) for r in chart):
            errors.append(f'图表指标 {metric} 没有有效来源值')
    state = {'title': record['title'], 'template': record['template'], 'bindings': resolved,
             'chart': chart, 'chart_metrics': record['chart_metrics']}
    if citations:
        state['citations'] = citations
    rendered = body_markdown(state) + evidence_markdown(citations)
    previous = record['generated'].get('state')
    changes = []
    if previous:
        previous_alias = {r['alias']: r for r in previous['bindings']}
        for current in resolved:
            old = previous_alias.get(current['alias'])
            if not old or any(old[k] != current[k] for k in ['value', 'formatted', 'run_id', 'metric']):
                changes.append({'alias': current['alias'], 'before': old['formatted'] if old else '未绑定', 'after': current['formatted'], 'source_changed': bool(old and old['run_id'] != current['run_id'])})
    status = 'invalid' if errors else 'new' if not previous else 'stale' if previous != state else 'synced'
    return {**record, 'preview': rendered, 'resolved': resolved, 'errors': errors, 'changes': changes, 'state': state, 'sync_status': status}


def resolve_citations(pid, references):
    from .ingestion import document, spans
    sources, errors, cache = [], [], {}
    for ref in references:
        key = ref['document_id']
        if key not in cache:
            try:
                doc = document(pid, key)
                wanted = {r['span_id'] for r in references if r['document_id'] == key}
                cache[key] = (doc, {s['id']: s for s in spans(doc) if s['id'] in wanted})
            except HTTPException:
                cache[key] = (None, {})
        doc, selected = cache[key]
        span = selected.get(ref['span_id'])
        if not doc or not span:
            errors.append(f'文献引用 {ref["alias"]} 的原文不存在或不属于当前项目，请重新选择')
        else:
            sources.append({**ref, 'title': doc['title'], 'filename': doc['filename'], 'page': span['page'], 'text': span['text']})
    return sources, errors


def validate_report(pid, body):
    runs = {r['id']: r for r in core.records('runs', pid)}
    aliases = [r.alias for r in body.bindings]
    if len(aliases) != len(set(aliases)):
        raise HTTPException(422, '变量名称不能重复')
    for binding in body.bindings:
        run = runs.get(binding.run_id)
        if not run or run['status'] != 'succeeded' or binding.metric not in run['metrics']:
            raise HTTPException(422, '变量必须绑定本项目成功完成的真实指标')
    if any(rid not in runs or runs[rid]['status'] != 'succeeded' for rid in body.chart_run_ids):
        raise HTTPException(422, '图表来源须为本项目已成功的运行')
    if len(set(body.chart_run_ids)) != len(body.chart_run_ids):
        raise HTTPException(422, '图表来源运行不能重复')
    if len({c.alias for c in body.citations}) != len(body.citations):
        raise HTTPException(422, '文献引用名称不能重复')
    _, errors = resolve_citations(pid, [c.model_dump() for c in body.citations])
    if errors:
        raise HTTPException(422, '；'.join(errors))


@router.post('/projects/{pid}/reports')
def create_report(pid: str, body: ReportBody):
    core.project(pid)
    validate_report(pid, body)
    rid = core.uid()
    with core.db() as conn:
        conn.execute('INSERT INTO reports (id,project_id,title,template,bindings,chart_run_ids,chart_metrics,generated,created,updated,citations) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (rid, pid, body.title, body.template, json.dumps([b.model_dump() for b in body.bindings]),
             json.dumps(body.chart_run_ids), json.dumps(body.chart_metrics), '{}', core.now(), core.now(), json.dumps([c.model_dump() for c in body.citations])))
    return resolve_report(report_record(pid, rid))


@router.put('/projects/{pid}/reports/{rid}')
def update_report(pid: str, rid: str, body: ReportBody):
    report_record(pid, rid)
    validate_report(pid, body)
    with core.db() as conn:
        conn.execute('UPDATE reports SET title=?, template=?, bindings=?, chart_run_ids=?, chart_metrics=?, updated=?, citations=? WHERE id=?',
            (body.title, body.template, json.dumps([b.model_dump() for b in body.bindings]), json.dumps(body.chart_run_ids), json.dumps(body.chart_metrics), core.now(), json.dumps([c.model_dump() for c in body.citations]), rid))
    return resolve_report(report_record(pid, rid))


@router.get('/projects/{pid}/reports/{rid}')
def get_report(pid: str, rid: str):
    return resolve_report(report_record(pid, rid))


@router.post('/projects/{pid}/reports/{rid}/generate')
def generate_report(pid: str, rid: str):
    record = resolve_report(report_record(pid, rid))
    if record['errors']:
        raise HTTPException(422, '；'.join(record['errors']))
    generation = core.uid()
    folder = core.DATA / 'reports' / rid / generation
    folder.mkdir(parents=True, exist_ok=True)
    content = '# ' + record['title'] + '\n\n' + record['preview'] + '\n\n## 结果来源\n\n'
    for binding in record['resolved']:
        content += f'- {binding["alias"]}：{binding["formatted"]}；{binding["run_name"]}；指标 {binding["metric"]}；运行 {binding["run_id"]}\n'
    content += '\n图表中的缺失值不补写为0。文稿的解释性判断由作者核对。\n'
    (folder / 'report.md').write_text(content, encoding='utf-8')
    result_rows = {(r['run_id'], r['metric']): [r['run_name'], r['metric'], r['value']] for r in record['resolved']}
    result_rows.update({(r['id'], metric): [r['name'], metric, r['metrics'].get(metric)]
                        for r in record['state']['chart'] for metric in record['chart_metrics']})
    write_csv(folder / 'results.csv', ['运行', '指标', '实际值'], result_rows.values())
    (folder / 'sources.json').write_text(json.dumps(record['state'], ensure_ascii=False, indent=2), encoding='utf-8')
    files = ['report.md', 'results.csv', 'sources.json']
    if record['state']['chart'] and record['chart_metrics']:
        with PLOT_LOCK:
            import matplotlib.pyplot as plt
            configure_plot()
            metrics = record['chart_metrics']
            fig, axes = plt.subplots(len(metrics), 1, figsize=(8, max(3, 3 * len(metrics))), squeeze=False)
            for axis, metric in zip(axes[:, 0], metrics):
                values = [(r['name'], r['metrics'].get(metric)) for r in record['state']['chart'] if type(r['metrics'].get(metric)) in (int, float)]
                axis.bar([name for name, _ in values], [value for _, value in values], color='#4265bc')
                axis.set_title(metric)
                axis.tick_params(axis='x', rotation=20)
            fig.tight_layout()
            fig.savefig(folder / 'figure.png')
            plt.close(fig)
        files.append('figure.png')
    generated = {'id': generation, 'version': record['generated'].get('version', 0) + 1,
                 'created': core.now(), 'state': record['state'], 'files': files}
    with core.db() as conn:
        conn.execute('UPDATE reports SET generated=? WHERE id=?', (json.dumps(generated, ensure_ascii=False), rid))
    return resolve_report(report_record(pid, rid))


@router.get('/projects/{pid}/reports/{rid}/artifacts/{name}')
def report_artifact(pid: str, rid: str, name: str):
    report = report_record(pid, rid)
    if name not in report['generated'].get('files', []) or Path(name).name != name:
        raise HTTPException(404, '成果文件不存在')
    return FileResponse(core.DATA / 'reports' / rid / report['generated']['id'] / name)


@router.get('/projects/{pid}/reports/{rid}/export')
def report_export(pid: str, rid: str):
    report = report_record(pid, rid)
    if not report['generated']:
        raise HTTPException(409, '请先生成成果')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in report['generated']['files']:
            archive.write(core.DATA / 'reports' / rid / report['generated']['id'] / name, name)
    return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="research-results.zip"'})


@router.get('/projects/{pid}/reports/{rid}/word')
def report_word(pid: str, rid: str, template: Literal['generic','school'] = 'generic'):
    record = report_record(pid, rid)
    generated = record['generated']
    if not generated:
        raise HTTPException(409, '请先生成成果，再导出对应版本的Word')
    from .report_docx import export_word
    from docx.opc.exceptions import PackageNotFoundError
    try:
        with PLOT_LOCK:
            template_path = core.DATA / 'templates' / 'school.docx' if template == 'school' else None
            if template_path and not template_path.is_file():
                raise HTTPException(409, '本机尚未安装学校模板')
            content = export_word(generated['state'], generated['version'], generated['created'], template_path)
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(422, 'Word 模板无法打开或缺少必要样式') from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers={'Content-Disposition': f'attachment; filename="research-report-v{generated["version"]}.docx"'})
