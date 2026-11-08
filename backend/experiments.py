"""Experiment runs and repository imports for the local workbench."""
import io
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import app as core
from .retrieval import retrieve

router = APIRouter(prefix='/api')
PROCESS_LOCK = threading.Lock()
PROCESSES = {}
ACTIVE = {'queued', 'running'}


def stop_runs():
    with PROCESS_LOCK:
        active = list(PROCESSES.items())
        with core.db() as conn:
            finished = core.now()
            for table in ('runs', 'experiment_series'):
                conn.execute(f"UPDATE {table} SET status='interrupted',finished=? WHERE status IN ('queued','running')", (finished,))
        for _, child in active:
            if child.poll() is None:
                child.kill()
    if shutil.which('docker'):
        for rid, _ in active:
            remove_container(rid)


def remove_container(rid):
    try:
        subprocess.run(['docker', 'rm', '-f', f'research-{rid}'], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


def regular_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    # Docker Desktop exposes some Linux links as Windows reparse points.
    attributes = getattr(info, 'st_file_attributes', 0)
    return stat.S_ISREG(info.st_mode) and not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT


def read_log(path):
    if not regular_file(path):
        return ''
    with path.open('rb') as stream:
        end = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, end - 120000))
        return stream.read(120000).decode('utf-8', errors='replace')[-30000:]


def collect_repository_outputs(source, output):
    reserved = {'config.json', 'run.log', 'repository-output'}
    remaining = 100 * 1024 * 1024
    count = 0
    for path in source.iterdir():
        if path.name.casefold() in reserved or not regular_file(path):
            continue
        size = path.stat().st_size
        if count >= 200 or size > remaining:
            continue
        shutil.copyfile(path, output / path.name)
        remaining -= size
        count += 1

def docker_available():
    if not shutil.which('docker'):
        return False
    try:
        return subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


@router.get('/runtime/status')
def runtime_status():
    docker = core.docker_available()
    try:
        ready = docker and subprocess.run(['docker', 'image', 'inspect', 'research-workbench:0.1'], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    return {'docker': docker, 'image_ready': ready}


class RepoBody(BaseModel):
    url: str


def unpack_repo(pid: str, name: str, content: bytes, url='', revision='uploaded'):
    rid = core.uid()
    dest = core.DATA / 'repositories' / rid
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        if sum(m.file_size for m in members) > 100 * 1024 * 1024 or len(members) > 10000:
            raise HTTPException(422, '仓库解压后须小于100MB且不超过10000个文件')
        roots = {m.filename.split('/')[0] for m in members if m.filename}
        strip_root = len(roots) == 1 and any('/' in m.filename for m in members) and all(m.is_dir() or '/' in m.filename for m in members)
        checked = []
        seen = set()
        for member in members:
            if '\\' in member.filename or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise HTTPException(422, '仓库包含不安全的路径或符号链接')
            parts = member.filename.rstrip('/').split('/')
            if any(not part or part in {'.', '..'} or part.endswith((' ', '.'))
                   or PureWindowsPath(part).is_reserved() or any(c in part for c in ':<>"|?*') for part in parts):
                raise HTTPException(422, '仓库包含不安全的路径')
            relative = '/'.join(parts[1:] if strip_root else parts)
            if relative and not member.is_dir() and '.git' not in relative.casefold().split('/'):
                key = relative.casefold()
                if key in seen:
                    raise HTTPException(422, '仓库包含重复路径')
                seen.add(key)
                checked.append((member, relative))
        if any('/'.join(path.split('/')[:i]) in seen for path in seen for i in range(1, len(path.split('/')))):
            raise HTTPException(422, '仓库文件与目录路径冲突')
        dest.mkdir(parents=True)
        for member, relative in checked:
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    files = [relative for _, relative in checked]
    with core.db() as conn:
        conn.execute('INSERT INTO repositories VALUES (?,?,?,?,?,?,?)', (rid, pid, name, url, revision, json.dumps(files), core.now()))
    return next(r for r in core.records('repositories', pid) if r['id'] == rid)


@router.post('/projects/{pid}/repositories/upload')
async def upload_repo(pid: str, file: UploadFile = File(...)):
    core.project(pid)
    content = await file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, '仓库压缩包最大25MB')
    try:
        return unpack_repo(pid, Path(file.filename or 'repository.zip').stem, content)
    except zipfile.BadZipFile:
        raise HTTPException(422, '请上传有效ZIP仓库')


@router.post('/projects/{pid}/repositories')
def github_repo(pid: str, body: RepoBody):
    core.project(pid)
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', body.url.strip())
    if not match:
        raise HTTPException(422, '请输入公开GitHub仓库首页地址，或上传ZIP')
    owner, repo = match.groups()
    try:
        with httpx.Client(timeout=45, follow_redirects=True) as client:
            info = client.get(f'https://api.github.com/repos/{owner}/{repo}')
            info.raise_for_status()
            branch = info.json()['default_branch']
            commit = client.get(f'https://api.github.com/repos/{owner}/{repo}/commits/{branch}')
            commit.raise_for_status()
            revision = commit.json()['sha']
            with client.stream('GET', f'https://codeload.github.com/{owner}/{repo}/zip/{revision}') as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 25 * 1024 * 1024:
                        raise HTTPException(413, '仓库大于25MB，请上传只包含必要实验文件的ZIP')
                    chunks.append(chunk)
    except (httpx.HTTPError, KeyError):
        raise HTTPException(502, '仓库下载失败。请检查公开地址、网络或改用ZIP上传。')
    return unpack_repo(pid, f'{owner}/{repo}', b''.join(chunks), body.url, revision)


@router.get('/projects/{pid}/repositories/{rid}/inspect')
def inspect_repo(pid: str, rid: str):
    repo = next((r for r in core.records('repositories', pid) if r['id'] == rid), None)
    if not repo:
        raise HTTPException(404, '仓库不存在')
    directory = core.DATA / 'repositories' / rid
    readme = next((f for f in repo['files'] if Path(f).name.lower() in {'readme.md', 'readme.rst', 'readme.txt'}), None)
    return {'entries': [f for f in repo['files'] if f.endswith('.py')],
            'requirements': [f for f in repo['files'] if Path(f).name in {'requirements.txt', 'pyproject.toml'}],
            'readme': (directory / readme).read_text(encoding='utf-8', errors='replace')[:20000] if readme else '未找到README',
            'files': repo['files'][:500]}


@router.post('/runtime/prepare')
def prepare_runtime():
    if not core.docker_available():
        raise HTTPException(409, '请先启动Docker Desktop')
    try:
        result = subprocess.run(['docker', 'build', '-t', 'research-workbench:0.1', '-f', str(core.ROOT / 'Dockerfile.runner'), str(core.ROOT)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    except subprocess.TimeoutExpired:
        raise HTTPException(408, '运行环境构建超时，请检查Docker网络并重试')
    if result.returncode:
        raise HTTPException(500, '环境构建失败：' + result.stderr[-2500:])
    return {'ready': True}


class RunBody(BaseModel):
    name: str = Field(default='一次实验', min_length=1, max_length=100)
    recipe: str = 'iris'
    standardize: bool = True
    regularization: float = Field(default=1, gt=0, le=1000)
    test_size: float = Field(default=0.3, ge=0.1, le=0.5)
    seed: int = Field(default=42, ge=0, le=2147483647)
    max_iter: int = Field(default=200, ge=10, le=2000)
    repository_id: str = ''
    entry: str = ''
    args: list[str] = Field(default_factory=list, max_length=30)
    timeout: int = Field(default=120, ge=10, le=1800)


def run_update(rid, **values):
    with core.db() as conn:
        conn.execute('UPDATE runs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?',
                     [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in values.values()] + [rid])


def run_record(pid, rid):
    row = next((r for r in core.records('runs', pid) if r['id'] == rid), None)
    if not row:
        raise HTTPException(404, '运行记录不存在')
    return row


def execute_run(pid, rid, config):
    if run_record(pid, rid)['status'] not in ACTIVE:
        return
    output = core.DATA / 'runs' / rid
    output.mkdir(parents=True, exist_ok=True)
    (output / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    recipe = config['recipe']
    if recipe == 'iris':
        command = [sys.executable, '-u', str(core.ROOT / 'backend' / 'experiment.py'), '--config', str(output / 'config.json'), '--output', str(output)]
        cwd = core.ROOT
    elif recipe == 'analysis':
        shutil.copyfile(core.DATA / 'datasets' / config['dataset_id'] / 'input.csv', output / 'input.csv')
        shutil.copyfile(core.ROOT / 'backend' / 'analysis_runner.py', output / 'analysis_runner.py')
        command = [sys.executable, '-u', str(output / 'analysis_runner.py'), '--input', str(output / 'input.csv'),
                   '--plan', str(output / 'config.json'), '--output', str(output)]
        cwd = core.ROOT
    else:
        repo_dir = core.DATA / 'repositories' / config['repository_id']
        repository_output = output / 'repository-output'
        repository_output.mkdir(exist_ok=True)
        command = ['docker', 'run', '--rm', '--name', f'research-{rid}', '--network', 'none', '--cpus', '2', '--memory', '2g',
                   '--pids-limit', '128', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
                   '--tmpfs', '/tmp:rw,size=128m', '--mount', f'type=bind,source={repo_dir},target=/workspace,readonly',
                   '--mount', f'type=bind,source={repository_output},target=/output', '-w', '/workspace',
                   '-e', 'RESEARCH_OUTPUT=/output', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'MPLCONFIGDIR=/tmp/matplotlib',
                   'research-workbench:0.1', 'python', '-u', config['entry'], *config['args']]
        cwd = core.ROOT
    log_path = output / 'run.log'
    start = time.monotonic()
    try:
        with log_path.open('w', encoding='utf-8') as log_file:
            log_file.write('执行：' + subprocess.list2cmdline(command) + '\n')
            log_file.flush()
            with PROCESS_LOCK:
                if run_record(pid, rid)['status'] not in ACTIVE:
                    return
                run_update(rid, status='running')
                child = subprocess.Popen(command, cwd=cwd, stdout=log_file, stderr=subprocess.STDOUT,
                                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'MPLCONFIGDIR': str(output / '.matplotlib')})
                PROCESSES[rid] = child
            try:
                code = child.wait(timeout=config['timeout'])
                state = 'succeeded' if code == 0 else 'failed'
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                state = 'timeout'
            recorded_state = run_record(pid, rid)['status']
            if recorded_state in {'cancelled', 'interrupted'}:
                state = recorded_state
        if recipe == 'repository' and state in {'succeeded', 'failed'}:
            collect_repository_outputs(repository_output, output)
        metrics = {}
        metrics_file = output / 'metrics.json'
        if regular_file(metrics_file) and metrics_file.stat().st_size <= 1024 * 1024:
            try:
                metrics = json.loads((output / 'metrics.json').read_text(encoding='utf-8'))
                metrics = {k: v for k, v in metrics.items() if type(v) in (int, float) and math.isfinite(v)} if isinstance(metrics, dict) else {}
            except (ValueError, OSError):
                pass
        artifacts = [f.name for f in output.iterdir() if regular_file(f)]
        with PROCESS_LOCK:
            recorded_state = run_record(pid, rid)['status']
            if recorded_state in {'cancelled', 'interrupted'}:
                state = recorded_state
            run_update(rid, status=state, metrics=metrics, artifacts=artifacts,
                       log=read_log(log_path) + f'\n实际耗时：{time.monotonic() - start:.2f}s', finished=core.now())
    except Exception as exc:
        with PROCESS_LOCK:
            if run_record(pid, rid)['status'] in ACTIVE:
                run_update(rid, status='failed', log=str(exc), finished=core.now())
    finally:
        with PROCESS_LOCK:
            PROCESSES.pop(rid, None)
        if recipe == 'repository':
            remove_container(rid)


def repository_run(pid, body):
    repo = next((r for r in core.records('repositories', pid) if r['id'] == body.repository_id), None)
    if not repo or body.entry not in repo['files'] or not body.entry.endswith('.py'):
        raise HTTPException(422, '请选择仓库中的Python入口文件')
    if not core.docker_available():
        raise HTTPException(409, '外部仓库运行需要已启动的Docker环境')
    if subprocess.run(['docker', 'image', 'inspect', 'research-workbench:0.1'], capture_output=True, timeout=5).returncode:
        raise HTTPException(409, '请先准备隔离运行环境')
    if any(len(a) > 500 for a in body.args):
        raise HTTPException(422, '参数过长')
    return repo


@router.post('/projects/{pid}/runs')
def start_run(pid: str, body: RunBody):
    core.project(pid)
    config = body.model_dump()
    if body.recipe not in {'iris', 'repository'}:
        raise HTTPException(422, '未知实验类型')
    if body.recipe == 'repository':
        config['revision'] = repository_run(pid, body)['revision']
    rid = core.uid()
    with core.db() as conn:
        conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)', (rid, pid, body.name, 'queued', json.dumps(config), '{}', '', '[]', core.now(), None))
    threading.Thread(target=execute_run, args=(pid, rid, config), daemon=True).start()
    return run_record(pid, rid)


@router.post('/projects/{pid}/plan')
def experiment_plan(pid: str, body: Question):
    core.project(pid)
    passages = retrieve(core.records('documents', pid), body.question)
    repos = core.records('repositories', pid)
    material = '\n\n'.join(f"[{p['citation']}] {p['text']}" for p in passages)
    material += '\n仓库文件：\n' + '\n'.join(f"{r['name']}: " + ', '.join(r['files'][:100]) for r in repos)
    output = core.model_json('目标：' + body.question + '\n生成实验执行计划，返回 {"steps":[{"title":"步骤","detail":"可执行安排或待确认信息"}],"unknowns":["缺少的条件"]}。只能使用现有仓库文件名，勿虚构论文结果。', material)
    if output is None:
        output = {'steps': [
            {'title': '核对目标与资料', 'detail': f'目标：{body.question}。已检索{len(passages)}段相关原文，先核对数据、参数与评价口径。'},
            {'title': '选择实验入口', 'detail': '内置Iris示例可直接运行；外部仓库请根据README选择Python入口和参数。'},
            {'title': '运行并保存真实结果', 'detail': '配置实验后执行；检查运行日志、metrics.json和输出文件。'},
            {'title': '执行变体并比较', 'detail': '修改一个有研究依据的参数，保存为另一条运行，比较真实指标与设定。'}],
            'unknowns': ['未配置模型：当前为固定流程指导，论文设定与代码对应需要作者核对。']}
    return {**output, 'evidence': passages, 'mode': 'model' if core.settings()['base_url'] else 'rule'}


@router.get('/projects/{pid}/runs/{rid}')
def get_run(pid: str, rid: str):
    record = run_record(pid, rid)
    path = core.DATA / 'runs' / rid / 'run.log'
    if record['status'] in ACTIVE:
        record['log'] = read_log(path)
    return record


@router.post('/projects/{pid}/runs/{rid}/cancel')
def cancel_run(pid: str, rid: str):
    with PROCESS_LOCK:
        record = run_record(pid, rid)
        if record['status'] not in {'running', 'queued'}:
            raise HTTPException(409, '此实验已经结束')
        run_update(rid, status='cancelled', finished=core.now())
        if (child := PROCESSES.get(rid)) and child.poll() is None:
            child.kill()
    return {'cancelled': True}


@router.post('/projects/{pid}/runs/{rid}/diagnose')
def diagnose_run(pid: str, rid: str):
    record = get_run(pid, rid)
    result = core.model_json('分析实际日志，返回 {"cause":"有日志依据的失败原因或未知","suggestions":["可操作建议"]}。不要声称已经修复。', record['log'][-15000:])
    if result is None:
        log = record['log']
        cause, suggestions = '需要结合日志继续检查', ['核对入口、参数、依赖与输入数据；可配置模型辅助分析。']
        if 'ModuleNotFoundError' in log:
            cause = '隔离环境缺少依赖'
            suggestions = ['将所需依赖加入Dockerfile.runner并重新准备隔离环境。外部代码不在宿主机运行。']
        elif 'Read-only file system' in log or 'PermissionError' in log:
            cause = '程序向只读仓库目录写入文件'
            suggestions = ['将结果目录改为环境变量RESEARCH_OUTPUT或参数指定的/output。']
        elif record['status'] == 'timeout':
            cause = '实验超过设定时限'
            suggestions = ['核对计算规模，或在真实资源允许时延长运行时限；缩减实验不能等同于完整复现。']
        elif record['status'] == 'succeeded':
            cause = '程序已成功退出'
            suggestions = ['成功退出不等同于复现论文结论，请核对结果文件、数据划分和评价口径。']
        result = {'cause': cause, 'suggestions': suggestions, 'mode': 'rule'}
    return result


@router.get('/projects/{pid}/runs/{rid}/artifacts/{name}')
def artifact(pid: str, rid: str, name: str):
    record = run_record(pid, rid)
    if name not in record['artifacts'] or Path(name).name != name:
        raise HTTPException(404, '成果文件不存在')
    path = core.DATA / 'runs' / rid / name
    if not regular_file(path):
        raise HTTPException(404, '成果文件不存在')
    if record['config']['recipe'] == 'repository':
        return FileResponse(path, filename=name, media_type='application/octet-stream', headers={'X-Content-Type-Options': 'nosniff'})
    return FileResponse(path)




@router.get('/projects/{pid}/export/reproduction.zip')
def export_runs(pid: str):
    p = core.project(pid)
    docs = core.records('documents', pid)
    runs = core.records('runs', pid)
    report = f'# {p["name"]}\n\n研究问题：{p["question"]}\n\n'
    report += '## 实际实验\n\n'
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(core.ROOT / 'backend' / 'experiment.py', 'builtin/experiment.py')
        archive.write(core.ROOT / 'backend' / 'replay_repository.py', 'replay_repository.py')
        archive.write(core.ROOT / 'Dockerfile.runner', 'Dockerfile.runner')
        archive.write(core.ROOT / 'requirements.txt', 'requirements.txt')
        for run in runs:
            report += f'### {run["name"]}\n\n状态：{run["status"]}\n\n配置：`{json.dumps(run["config"], ensure_ascii=False)}`\n\n真实指标：`{json.dumps(run["metrics"])}`\n\n'
            folder = core.DATA / 'runs' / run['id']
            for path in folder.glob('*'):
                if regular_file(path):
                    archive.write(path, f'runs/{run["id"]}/{path.name}')
            if run['config']['recipe'] == 'iris':
                report += f'复跑：`python builtin/experiment.py --config runs/{run["id"]}/config.json --output rerun/{run["id"]}`\n\n'
            elif run['config']['recipe'] == 'analysis':
                report += f'复跑：`python runs/{run["id"]}/analysis_runner.py --input runs/{run["id"]}/input.csv --plan runs/{run["id"]}/config.json --output rerun/{run["id"]}`\n\n'
            elif run['config']['recipe'] == 'repository':
                repo_id = run['config']['repository_id']
                report += f'隔离复跑：`python replay_repository.py --config runs/{run["id"]}/config.json --repository repositories/{repo_id} --output rerun/{run["id"]}`\n\n'
        report += '## 验证范围\n\n内置Iris案例是工作流程示例，不是已发表论文的完整复现。外部实验需要作者核对论文设定、数据与指标。未运行的实验不补写结果。\n'
        archive.writestr('复现说明.md', report)
        archive.writestr('literature.json', json.dumps(docs, ensure_ascii=False, indent=2))
        for repo in core.records('repositories', pid):
            for name in repo['files']:
                path = core.DATA / 'repositories' / repo['id'] / name
                if path.is_file():
                    archive.write(path, f'repositories/{repo["id"]}/{name}')
    return Response(memory.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="reproduction.zip"'})


@router.get('/projects/{pid}/experiment-workspace')
def workspace(pid: str):
    core.project(pid)
    tables = ('runs', 'repositories', 'datasets', 'experiment_series', 'research_notes')
    return {table: core.records(table, pid) for table in tables}
