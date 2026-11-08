"""Dataset import, cleaning and reproducible descriptive analysis."""
import csv
import io
import json
import math
from pathlib import Path
import threading
from typing import Literal
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from openpyxl import load_workbook
from pydantic import BaseModel, Field, model_validator

from . import app as core
from .experiments import regular_file
from .analysis_runner import MISSING, number

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
