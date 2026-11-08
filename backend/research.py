"""Research decisions and bounded, paired-seed experiment comparisons."""
import csv
import io
import json
import math
import statistics
import threading
from typing import Literal
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from . import app as core
from .experiments import regular_file

router = APIRouter(prefix='/api')
ACTIVE = {'queued', 'running'}


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
    runs = [core.run_record(pid, rid) for rid in note['run_ids']]
    linked_reports = []
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


class SeriesBody(BaseModel):
    name: str = Field(default='多种子对照实验', min_length=1, max_length=100)
    factor: Literal['standardize', 'regularization', 'argument'] = 'standardize'
    values: list[float] = Field(default_factory=lambda: [.1, 10], max_length=3)
    seeds: list[int] = Field(default_factory=lambda: [42, 43, 44], min_length=2, max_length=5)
    base: core.RunBody = Field(default_factory=core.RunBody)
    note_id: str = ''
    parameter: str = Field(default='--regularization', pattern=r'^--[A-Za-z][A-Za-z0-9_-]{0,49}$')
    seed_parameter: str = Field(default='--seed', pattern=r'^--[A-Za-z][A-Za-z0-9_-]{0,49}$')
    control_value: float = 1
    metric: str = Field(default='accuracy', min_length=1, max_length=100)

    @model_validator(mode='after')
    def limits(self):
        if not self.metric.strip():
            raise ValueError('请填写实际指标名称')
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 or s > 2147483647 for s in self.seeds):
            raise ValueError('随机种子须不重复且位于0至2147483647')
        if self.base.recipe not in {'iris', 'repository'}:
            raise ValueError('请选择内置Iris或外部仓库实验')
        if self.base.recipe == 'repository':
            if self.factor != 'argument' or self.parameter == self.seed_parameter:
                raise ValueError('外部仓库需选择数值参数对照，变体参数与种子参数须不同')
            if not self.values or all(v == self.control_value for v in self.values) or len(set(self.values)) != len(self.values) or any(not math.isfinite(v) for v in [self.control_value, *self.values]):
                raise ValueError('对照与变体需为有限数值，变体值不能重复')
            if len(self.base.args) > 26 or any(a.split('=', 1)[0] in {self.parameter, self.seed_parameter} for a in self.base.args):
                raise ValueError('固定参数最多26项，不能重复设置变体或种子参数')
        elif self.factor == 'argument':
            raise ValueError('命令行参数对照仅适用于外部仓库')
        if self.factor == 'regularization' and (not self.values or len(set(self.values)) != len(self.values) or any(not 0 < v <= 1000 for v in self.values)):
            raise ValueError('C变体须不重复且位于0至1000（不含0）')
        return self


def series_update(sid, status):
    with core.db() as conn:
        conn.execute('UPDATE experiment_series SET status=?,finished=? WHERE id=?', (status, core.now() if status not in ACTIVE else None, sid))


def execute_series(pid, sid):
    try:
        with core.PROCESS_LOCK:
            series = item('experiment_series', pid, sid)
            if series['status'] not in ACTIVE:
                return
            series_update(sid, 'running')
        for rid in series['run_ids']:
            if item('experiment_series', pid, sid)['status'] not in ACTIVE:
                return
            run = core.run_record(pid, rid)
            if run['status'] in ACTIVE:
                core.execute_run(pid, rid, run['config'])
        with core.PROCESS_LOCK:
            if item('experiment_series', pid, sid)['status'] in ACTIVE:
                states = [core.run_record(pid, r)['status'] for r in series['run_ids']]
                series_update(sid, 'succeeded' if all(s == 'succeeded' for s in states) else 'partial')
    except Exception as exc:
        with core.PROCESS_LOCK:
            if item('experiment_series', pid, sid)['status'] in ACTIVE:
                series_update(sid, 'failed')
                with core.db() as conn:
                    conn.execute("UPDATE runs SET status='failed',log=?,finished=? WHERE project_id=? AND status='queued' AND json_extract(config,'$.series_id')=?", (str(exc), core.now(), pid, sid))


@router.post('/projects/{pid}/experiment-series')
def create_series(pid: str, body: SeriesBody):
    core.project(pid)
    note = item('research_notes', pid, body.note_id) if body.note_id else None
    base = body.base.model_dump()
    key = body.factor
    repo = core.repository_run(pid, body.base) if body.base.recipe == 'repository' else None
    control = body.control_value if repo else base.get(key)
    values = [control, not control] if key == 'standardize' else [control, *[v for v in body.values if v != control]]
    if len(values) < 2:
        raise HTTPException(422, '至少需要一个不同于对照的变体')
    sid, run_ids, variants = core.uid(), [], []
    for i, value in enumerate(values):
        label = ('标准化开启' if value else '标准化关闭') if key == 'standardize' else f'{body.parameter if repo else "C"}={value:g}'
        variants.append({'index': i, 'label': label, 'value': value})
    config = {'factor': key, 'variants': variants, 'seeds': body.seeds, 'base': base, 'note_id': body.note_id, 'metric': body.metric if repo else 'accuracy'}
    if repo:
        config.update(parameter=body.parameter, seed_parameter=body.seed_parameter, revision=repo['revision'])
    with core.db() as conn:
        for seed in body.seeds:
            for variant in variants:
                rid = core.uid()
                name = f"{body.name[:65]} · {variant['label']} · seed={seed}"
                run_config = {**base, key: variant['value'], 'seed': seed, 'name': name, 'series_id': sid, 'variant_index': variant['index'], 'variant_label': variant['label']}
                if repo:
                    run_config['args'] = [*base['args'], body.seed_parameter, str(seed), body.parameter, format(variant['value'], '.17g')]
                    run_config['revision'] = repo['revision']
                conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)', (rid, pid, name, 'queued', json.dumps(run_config), '{}', '', '[]', core.now(), None))
                run_ids.append(rid)
        if note and len(set(note['run_ids']) | set(run_ids)) > 30:
            raise HTTPException(422, '关联后该研究设想超过30条运行，请新建另一条记录')
        conn.execute('INSERT INTO experiment_series VALUES (?,?,?,?,?,?,?,?)', (sid, pid, body.name, 'queued', json.dumps(config), json.dumps(run_ids), core.now(), None))
        if note:
            outcome = 'testing' if note['outcome'] == 'planned' else note['outcome']
            conn.execute('UPDATE research_notes SET run_ids=?,outcome=?,updated=? WHERE id=?', (json.dumps([*note['run_ids'], *run_ids]), outcome, core.now(), note['id']))
    threading.Thread(target=execute_series, args=(pid, sid), daemon=True).start()
    return item('experiment_series', pid, sid)


def summarize_series(pid, series):
    runs = [core.run_record(pid, rid) for rid in series['run_ids']]
    metric = series['config'].get('metric', 'accuracy')
    summaries = []
    paired = []
    control = {r['config']['seed']: r['metrics'][metric] for r in runs if r['config']['variant_index'] == 0 and r['status'] == 'succeeded' and metric in r['metrics']}
    for variant in series['config']['variants']:
        subset = [r for r in runs if r['config']['variant_index'] == variant['index']]
        scores = [r['metrics'][metric] for r in subset if r['status'] == 'succeeded' and metric in r['metrics']]
        deltas = []
        for run in subset:
            seed = run['config']['seed']
            if variant['index'] and run['status'] == 'succeeded' and metric in run['metrics'] and seed in control:
                delta = run['metrics'][metric] - control[seed]
                deltas.append(delta)
                paired.append({'variant': variant['label'], 'seed': seed, 'control': control[seed], 'value': run['metrics'][metric], 'delta': delta, 'run_id': run['id']})
        summaries.append({**variant, 'n': len(scores), 'expected': len(series['config']['seeds']),
            'mean': statistics.mean(scores) if scores else None, 'std': statistics.stdev(scores) if len(scores) > 1 else None,
            'paired_n': len(deltas), 'paired_mean_delta': statistics.mean(deltas) if deltas else None,
            'positive_pairs': sum(d > 0 for d in deltas), 'negative_pairs': sum(d < 0 for d in deltas), 'ties': sum(d == 0 for d in deltas)})
    return {**series, 'runs': runs, 'summary': summaries, 'paired': paired,
        'completed': sum(r['status'] not in ACTIVE for r in runs),
        'notes': ['外部仓库接收相同的种子参数；需作者核对代码是否真正设置种子、数据划分与指标口径。' if series['config']['base']['recipe'] == 'repository' else '每个变体使用同一组种子、分层训练/测试划分比例和评价指标；一次只改变一个因素。',
                  '配对差值为相同种子的变体指标减去对照指标，仅纳入双方成功且存在指标的配对。',
                  '不同划分之间样本可能重叠；重复划分不等于独立样本实验。样本标准差不作为显著性检验。',
                  '内置Iris仅用于验证流程；本功能不自动判断研究新颖性或支持论文结论。']}


@router.get('/projects/{pid}/experiment-series/{sid}')
def get_series(pid: str, sid: str):
    return summarize_series(pid, item('experiment_series', pid, sid))


@router.post('/projects/{pid}/experiment-series/{sid}/cancel')
def cancel_series(pid: str, sid: str):
    with core.PROCESS_LOCK:
        series = item('experiment_series', pid, sid)
        if series['status'] not in ACTIVE:
            raise HTTPException(409, '该对照实验已结束')
        series_update(sid, 'cancelled')
    for rid in series['run_ids']:
        try:
            core.cancel_run(pid, rid)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    return get_series(pid, sid)


@router.get('/projects/{pid}/experiment-series/{sid}/export')
def export_series(pid: str, sid: str):
    data = get_series(pid, sid)
    if data['status'] in ACTIVE:
        raise HTTPException(409, '等待执行结束或停止后导出，避免读取仍在写入的文件')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('comparison.json', json.dumps(data, ensure_ascii=False, indent=2))
        csv_buffer = io.StringIO(newline='')
        writer = csv.writer(csv_buffer)
        def safe(value):
            return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
        writer.writerow([safe(v) for v in ['variant', 'seed', 'control_' + data['config']['metric'], data['config']['metric'], 'delta', 'run_id']])
        for p in data['paired']:
            writer.writerow([safe(v) for v in [p['variant'], p['seed'], p['control'], p['value'], p['delta'], p['run_id']]])
        archive.writestr('paired-results.csv', '\ufeff' + csv_buffer.getvalue())
        external = data['config']['base']['recipe'] == 'repository'
        archive.write(core.ROOT / 'backend' / 'experiment.py', 'experiment.py')
        if external:
            repo = next((r for r in core.records('repositories', pid) if r['id'] == data['config']['base']['repository_id']), None)
            if not repo:
                raise HTTPException(404, '导出所需的仓库不存在')
            archive.write(core.ROOT / 'backend' / 'replay_repository.py', 'replay_repository.py')
            for name in repo['files']:
                path = core.DATA / 'repositories' / repo['id'] / name
                if regular_file(path):
                    archive.write(path, 'repository/' + name)
            archive.write(core.ROOT / 'Dockerfile.runner', 'Dockerfile.runner')
        archive.write(core.ROOT / 'requirements.txt', 'requirements.txt')
        instructions = '# 多种子对照实验\n\n' + '\n'.join('- ' + n for n in data['notes']) + '\n\n## 独立复跑\n\n'
        for run in data['runs']:
            for path in (core.DATA / 'runs' / run['id']).glob('*'):
                if regular_file(path):
                    archive.write(path, f"runs/{run['id']}/{path.name}")
            if external and (core.DATA / 'runs' / run['id'] / 'config.json').exists():
                instructions += f"- `python replay_repository.py --config runs/{run['id']}/config.json --repository repository --output replay/{run['id']}`\n"
            if not external and (core.DATA / 'runs' / run['id'] / 'config.json').exists():
                instructions += f"- `python experiment.py --config runs/{run['id']}/config.json --output replay/{run['id']}`\n"
        if external:
            instructions += '\n外部仓库源码在repository/，各次实际命令保留在runs/*/run.log，参数在config.json。按原Docker隔离配置重新运行；不要把外部代码直接在宿主机执行。相同种子参数不保证上游代码正确使用种子。\n'
        archive.writestr('README.md', instructions)
    return Response(buffer.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="paired-experiments.zip"'})
