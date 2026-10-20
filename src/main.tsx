import React, { useState, useEffect, useCallback, useRef, lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { FlaskConical, Library, Workflow, ChartNoAxesCombined, Settings, Plus, ArrowRight, ArrowUpRight, Upload, Download, Play, FileText, Check, X, PanelLeftClose, PanelLeftOpen, BookOpen, Search, Square, GitBranch, CircleHelp, Layers, ExternalLink, Trash2, LoaderCircle, CheckCircle2, AlertCircle, Terminal, Pencil } from 'lucide-react';
import './styles.css';
import { api, post, type MatrixField, type Doc, type Run, type Repo, type Project, type Evidence, type Answer } from './api';
import { AnalysisModule, SyncModule } from './ResearchModules';
import { ResearchCockpit } from './ResearchCockpit';
import './theme.css';
import './library.css';
import SourcePanel from './SourcePanel';

const PaperReader = lazy(() => import('./PaperReader'));
const DocumentStructure = lazy(() => import('./ResearchLibrary').then(m => ({ default: m.DocumentStructure })));
const EvidenceTasks = lazy(() => import('./ResearchLibrary').then(m => ({ default: m.EvidenceTasks })));

type Page = 'overview' | 'reproduce' | 'sync' | 'analysis' | 'read';
type Status = { docker: boolean; image_ready: boolean; model_configured: boolean };

const fields = [['method', '研究方法'], ['data', '数据与样本'], ['metrics', '评价指标'], ['limitations', '明确局限']] as const;
const statuses: Record<string, string> = { queued: '等待运行', running: '运行中', succeeded: '已完成', failed: '运行失败', timeout: '已超时', cancelled: '已取消', interrupted: '运行中断' };
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const modules = [
  { id: 'overview', title: '总览', desc: '研究与实验记录', icon: GitBranch },
  { id: 'reproduce', title: '研复', desc: '实验复现', icon: FlaskConical },
  { id: 'sync', title: '研迹', desc: '成果同步', icon: Workflow },
  { id: 'analysis', title: '研析', desc: '数据分析', icon: ChartNoAxesCombined },
  { id: 'read', title: '研读', desc: '文献与开题', icon: Library }
] as const;

function App() {
  const [page, setPage] = useState<Page>('overview');
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [status, setStatus] = useState<Status>({ docker: false, image_ready: false, model_configured: false });
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [modal, setModal] = useState<'project' | 'settings' | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [model, setModel] = useState({ base_url: '', model: '', api_key: '', has_key: false });
  const [selectedSource, setSelectedSource] = useState<{ document: Doc; span?: string } | null>(null);
  const activeProject = useRef('');

  const refresh = useCallback(async (id: string) => {
    const data = await api('/projects/' + id); activeProject.current = id; setProject(data); return data as Project;
  }, []);
  const refreshStatus = useCallback(async () => setStatus(await api('/status')), []);
  useEffect(() => {
    (async () => {
      let list = await api('/projects');
      if (!list.length) { const p = await post('/projects', { name: '我的科研项目' }); list = [p]; }
      setProjects(list); const id = localStorage.getItem('research-project');
      await refresh(list.some((p: Project) => p.id === id) ? id : list[0].id);
      await refreshStatus();
    })().catch(e => setError(e.message));
  }, [refresh, refreshStatus]);
  useEffect(() => {
    if (project) localStorage.setItem('research-project', project.id);
  }, [project?.id]);
  useEffect(() => {
    if (!project || !project.runs.some(r => ['queued', 'running'].includes(r.status)) && !project.experiment_series?.some(s => ['queued', 'running'].includes(s.status)) && !project.documents.some(d => d.ingestion && ['queued', 'running'].includes(d.ingestion.status))) return;
    const timer = window.setInterval(() => refresh(project.id).catch(e => setError(e.message)), 1500);
    return () => clearInterval(timer);
  }, [project?.id, project?.runs.map(r => r.status).join(','), project?.experiment_series?.map(s => s.status).join(','), project?.documents.map(d => d.ingestion?.status).join(','), refresh]);
  useEffect(() => {
    if (!modal) return;
    const dialog = document.querySelector<HTMLDialogElement>('#app-dialog'); dialog?.showModal();
    return () => dialog?.close();
  }, [modal]);
  const action = async (key: string, work: () => Promise<any>, success = '') => {
    setError(''); setNotice(''); setBusy(key);
    try { await work(); if (activeProject.current) await refresh(activeProject.current); if (success) setNotice(success); }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(''); }
  };
  const source = (did: string, sid?: string) => {
    const document = project?.documents.find(d => d.id === did); if (document) setSelectedSource({ document, span: sid });
  };
  const openSettings = async () => {
    try { const saved = await api('/settings'); setModel({ ...saved, api_key: '' }); setModal('settings'); } catch (e) { setError((e as Error).message); }
  };

  return <div className="app-shell">
    <aside id="workspace-navigation" className={'sidebar ' + (mobileNav ? 'open' : '')}>
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('overview'); }}><span className="brand-mark"><Layers size={23} /></span><span>研舟<small>RESEARCH WORKSPACE</small></span></a>
      <div className="workspace-picker"><label htmlFor="project-picker">当前研究项目</label><select id="project-picker" value={project?.id || ''} onChange={e => refresh(e.target.value).catch(e => setError(e.message))}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><button className="icon-button" title="新建项目" aria-label="新建项目" onClick={() => { setName(''); setQuestion(''); setModal('project'); }}><Plus size={17}/></button></div>
      <nav aria-label="科研功能">{modules.map(m => <button key={m.id} className={'nav-item ' + (page === m.id ? 'active' : '')} onClick={() => { setPage(m.id); setMobileNav(false); setSelectedSource(null); }}><m.icon size={19}/><span>{m.title}<small>{m.desc}</small></span>{page === m.id && <span className="nav-dot"/>}</button>)}</nav>
      <div className="sidebar-note"><BookOpen size={17}/><p>让每个结论<br/>都有可回看的依据。</p></div>
      <div className="sidebar-bottom"><button onClick={openSettings}><Settings size={17}/>模型与运行设置</button><div className="local-label"><span className="status-dot"/>本地工作空间<small>v0.1</small></div></div>
    </aside>
    {mobileNav && <button className="nav-backdrop" aria-label="关闭导航" onClick={() => setMobileNav(false)}/>}
    <div className="main-shell">
      <header className="topbar"><div><button className="mobile-toggle icon-button" aria-label="展开导航" aria-expanded={mobileNav} aria-controls="workspace-navigation" onClick={() => setMobileNav(!mobileNav)}>{mobileNav ? <PanelLeftClose size={20}/> : <PanelLeftOpen size={20}/>}</button><span className="breadcrumb">研究项目<span>/</span><b>{project?.name || '载入中'}</b></span></div><div className="topbar-right"><span className={'system-state ' + (status.model_configured ? 'ready' : '')}><span className="status-dot"/>{status.model_configured ? '模型已连接配置' : '原文检索模式'}</span><button className="icon-button" onClick={openSettings} aria-label="打开设置"><Settings size={18}/></button></div></header>
      <main className={page === 'overview' ? 'cockpit-page' : ''}>
        {(error || notice) && <div role={error ? 'alert' : 'status'} className={'feedback ' + (error ? 'error' : 'success')}>{error ? <AlertCircle size={18}/> : <CheckCircle2 size={18}/>}<span>{error || notice}</span><button className="icon-button" aria-label="关闭提示" onClick={() => { setError(''); setNotice(''); }}><X size={16}/></button></div>}
        {!project ? <div className="page-loading"><LoaderCircle className="spin"/>正在打开工作空间…</div> : <>
          {page === 'overview' && <ResearchCockpit key={project.id} project={project} busy={busy} action={action} source={source} go={setPage} question={<ProjectQuestion project={project} action={action}/>}/>}
          {page === 'reproduce' && <Reproduce key={project.id} project={project} status={status} busy={busy} action={action} refreshStatus={refreshStatus} source={source} goRead={() => setPage('read')} />}
          {page === 'read' && <Read key={project.id} project={project} busy={busy} action={action} source={source} modelConfigured={status.model_configured} settings={openSettings} />}
          {page === 'sync' && <SyncModule key={project.id} project={project} busy={busy} action={action}/>}
          {page === 'analysis' && <AnalysisModule key={project.id} project={project} busy={busy} action={action}/>}
        </>}
      </main>
      <footer>研究判断由你掌握。工作台保存实际资料与运行结果。</footer>
    </div>
    {selectedSource && <SourcePanel projectId={project!.id} selected={selectedSource} close={() => setSelectedSource(null)}/>}
    {modal && <dialog id="app-dialog" className="modal" onCancel={() => setModal(null)}><div className="modal-header"><h2>{modal === 'project' ? '新建研究项目' : '模型与运行设置'}</h2><button className="icon-button" aria-label="关闭弹窗" onClick={() => setModal(null)}><X size={20}/></button></div>
      {(error || notice) && <p className={'feedback ' + (error ? 'error' : 'success')} role={error ? 'alert' : 'status'}>{error || notice}</p>}
      {modal === 'project' ? <form onSubmit={e => { e.preventDefault(); action('create', async () => { const p = await post('/projects', { name, question }); setProjects(await api('/projects')); await refresh(p.id); setModal(null); }, '研究项目已创建'); }}>
        <label>项目名称<input autoFocus required maxLength={100} value={name} onChange={e => setName(e.target.value)} placeholder="例如：图像分类方法的复现实验"/></label><label>研究问题<textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="你希望通过资料和实验回答什么？" rows={3}/></label><div className="modal-actions"><button type="button" className="button secondary" onClick={() => setModal(null)}>取消</button><button className="button primary" disabled={!!busy}>创建项目<ArrowRight size={16}/></button></div>
      </form> : <form onSubmit={e => { e.preventDefault(); action('settings', async () => { await api('/settings', { method: 'PUT', body: JSON.stringify(model) }); await refreshStatus(); }, '模型配置已保存'); }}>
        <p className="muted">可连接兼容 Chat Completions 的服务。未配置时，仍可检索原文、整理资料和运行实验。</p><label>服务地址<input value={model.base_url} onChange={e => setModel({ ...model, base_url: e.target.value })} placeholder="https://api.example.com/v1"/></label><label>模型名称<input value={model.model} onChange={e => setModel({ ...model, model: e.target.value })} placeholder="服务提供方的模型名称"/></label><label>API密钥<input type="password" autoComplete="off" value={model.api_key} onChange={e => setModel({ ...model, api_key: e.target.value })} placeholder={model.has_key ? '已保存；留空保留现有密钥' : '仅保存在本机，不回传至界面'}/></label><p className="caption">模型分析会将选中的文献片段或日志发送给你配置的服务。</p>
        <div className="runtime-line"><span className={'status-dot ' + (status.docker ? '' : 'offline')}/><span>Docker {status.docker ? '已启动' : '未启动'}</span><button type="button" className="text-button" onClick={() => action('runtime', async () => { await post('/runtime/prepare'); await refreshStatus(); }, '隔离环境已准备') } disabled={!!busy || !status.docker}>{busy === 'runtime' ? '正在准备环境…' : status.image_ready ? '重新准备隔离环境' : '准备隔离运行环境'}</button></div>
        <div className="modal-actions"><button type="button" className="button secondary" disabled={!!busy} onClick={() => action('testmodel', async () => { const result = await post('/settings/test'); if (!result.ok) throw new Error('模型未通过连接测试'); }, '模型连接测试成功')}>测试已保存配置</button><button className="button primary" disabled={!!busy}>保存配置<Check size={16}/></button></div>
      </form>}
    </dialog>}
  </div>;
}

type SharedProps = { project: Project; busy: string; action: (key: string, work: () => Promise<any>, success?: string) => Promise<void>; source: (did: string, sid?: string) => void };
function ProjectQuestion({ project, action }: Pick<SharedProps, 'project' | 'action'>) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(project.question);
  return <section className="question-strip"><div className="question-symbol"><CircleHelp size={19}/></div><div><span className="small-label">当前研究问题</span>{editing ? <form onSubmit={e => { e.preventDefault(); action('question', async () => { await api('/projects/' + project.id, { method: 'PATCH', body: JSON.stringify({ name: project.name, question: value }) }); setEditing(false); }); }}><textarea value={value} onChange={e => setValue(e.target.value)} rows={2} required autoFocus/><div className="inline-actions"><button className="text-button">保存</button><button type="button" className="text-button muted" onClick={() => setEditing(false)}>取消</button></div></form> : <p>{project.question || '先写下一个明确的问题，连接你的文献与实验。'}</p>}</div>{!editing && <button className="icon-button" title="编辑研究问题" aria-label="编辑研究问题" onClick={() => { setValue(project.question); setEditing(true); }}><Pencil size={16}/></button>}</section>;
}

function Reproduce({ project, busy, action, status, refreshStatus, source, goRead }: SharedProps & { status: Status; refreshStatus: () => Promise<void>; goRead: () => void }) {
  const [tab, setTab] = useState<'setup' | 'results'>('setup');
  const [recipe, setRecipe] = useState('iris');
  const [config, setConfig] = useState({ name: '标准化特征 · 原方案', standardize: true, regularization: 1, test_size: 0.3, seed: 42, max_iter: 200, timeout: 120 });
  const [repoUrl, setRepoUrl] = useState('');
  const [repoId, setRepoId] = useState(project.repositories[0]?.id || '');
  const [entry, setEntry] = useState('');
  const [args, setArgs] = useState('');
  const [inspection, setInspection] = useState<any>(null);
  const [selectedRun, setSelectedRun] = useState('');
  const [runDetail, setRunDetail] = useState<Run | null>(null);
  const [diagnosis, setDiagnosis] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [comparison, setComparison] = useState<string[]>([]);
  const current = project.runs.find(r => r.id === selectedRun) || project.runs[0];
  useEffect(() => {
    let active = true;
    if (current) api(`/projects/${project.id}/runs/${current.id}`).then(data => { if (active) setRunDetail(data); }).catch(() => {});
    return () => { active = false; };
  }, [current?.id, current?.status, project.runs]);
  useEffect(() => {
    if (repoId) api(`/projects/${project.id}/repositories/${repoId}/inspect`).then(data => { setInspection(data); setEntry(data.entries[0] || ''); }).catch(() => {});
  }, [repoId, project.id]);
  const uploadRepo = (files: FileList | null) => {
    if (!files?.[0]) return;
    action('repo', async () => { const body = new FormData(); body.append('file', files[0]); const repo = await api(`/projects/${project.id}/repositories/upload`, { method: 'POST', body }); setRepoId(repo.id); }, '仓库已导入，尚未执行代码');
  };
  const start = () => action('run', async () => {
    const result = await post(`/projects/${project.id}/runs`, { ...config, recipe, repository_id: repoId, entry, args: args.split('\n').map(a => a.trim()).filter(Boolean) });
    setSelectedRun(result.id); setRunDetail(null); setTab('results'); setDiagnosis(null);
  }, '实验已提交，结果由实际运行产生');
  const compareRuns = project.runs.filter(r => comparison.includes(r.id));
  const metricKeys = [...new Set(compareRuns.flatMap(r => Object.keys(r.metrics)))];
  return <>
    <div className="page-heading"><div><h1>实验复现</h1><p>把论文中的实验，变成可执行、可核对的研究记录。</p></div><a className="button secondary" href={`/api/projects/${project.id}/export/reproduction.zip`}><Download size={16}/>导出复现材料</a></div>
    <ProjectQuestion project={project} action={action}/>
    <div className="workflow-strip">{[{ title: '研究资料', detail: project.documents.length ? `${project.documents.length}篇已导入` : '等待导入', done: project.documents.length > 0 }, { title: '实验配置', detail: '选择入口与设定', done: false }, { title: '真实运行', detail: project.runs.length ? `${project.runs.length}条记录` : '尚未运行', done: project.runs.length > 0 }, { title: '结果与交付', detail: '对比 · 导出', done: project.runs.some(r => r.status === 'succeeded') }].map((s, i) => <React.Fragment key={s.title}><div className="workflow-step"><span className={'step-num ' + (s.done ? 'done' : '')}>{s.done ? <Check size={13}/> : i + 1}</span><span>{s.title}<small>{s.detail}</small></span></div>{i < 3 && <ArrowRight size={14} className="step-arrow"/>}</React.Fragment>)}</div>
    <div className="tabs"><button className={tab === 'setup' ? 'selected' : ''} onClick={() => setTab('setup')}>实验准备</button><button className={tab === 'results' ? 'selected' : ''} onClick={() => setTab('results')}>运行记录<span className="count">{project.runs.length}</span></button></div>
    {tab === 'setup' ? <div className="reproduce-grid"><section className="surface config-surface"><div className="section-heading"><h2>配置一次实验</h2><span className="caption">所有设定随运行保存</span></div>
      <div className="segmented"><button className={recipe === 'iris' ? 'selected' : ''} onClick={() => setRecipe('iris')}>内置流程示例</button><button className={recipe === 'repository' ? 'selected' : ''} onClick={() => setRecipe('repository')}>我的代码仓库</button></div>
      {recipe === 'iris' ? <><div className="recipe-description"><FlaskConical size={20}/><div><b>Iris分类 · 逻辑回归</b><p>比较标准化与未标准化特征。150个真实样本，CPU运行。</p></div><span className="badge neutral">流程示例</span></div><p className="caption">此案例用于体验工作流程，不是已发表论文的复现。结果需实际运行后获得。</p>
        <label>运行名称<input value={config.name} onChange={e => setConfig({ ...config, name: e.target.value })}/></label>
        <div className="form-grid"><label>正则化参数 C<input type="number" min="0.001" max="1000" step="0.1" value={config.regularization} onChange={e => setConfig({ ...config, regularization: Number(e.target.value) })}/></label><label>测试集比例<input type="number" min="0.1" max="0.5" step="0.05" value={config.test_size} onChange={e => setConfig({ ...config, test_size: Number(e.target.value) })}/></label><label>随机种子<input type="number" min="0" value={config.seed} onChange={e => setConfig({ ...config, seed: Number(e.target.value) })}/></label><label>最大迭代次数<input type="number" min="10" max="2000" value={config.max_iter} onChange={e => setConfig({ ...config, max_iter: Number(e.target.value) })}/></label></div>
        <label className="checkbox-row"><input type="checkbox" checked={config.standardize} onChange={e => setConfig({ ...config, standardize: e.target.checked, name: e.target.checked ? '标准化特征 · 原方案' : '关闭标准化 · 变体' })}/><span>启用特征标准化<small>关闭后可作为同一划分下的变体实验</small></span></label>
      </> : <><div className="repo-import"><label>公开GitHub仓库<div className="input-action"><input value={repoUrl} onChange={e => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repository"/><button className="button secondary" disabled={!!busy || !repoUrl} onClick={() => action('repo', async () => { const repo = await post(`/projects/${project.id}/repositories`, { url: repoUrl }); setRepoId(repo.id); }, '仓库已导入，尚未执行代码')}>{busy === 'repo' ? <LoaderCircle className="spin" size={15}/> : <GitBranch size={15}/>}导入</button></div></label><label className="file-button compact"><Upload size={15}/>或者上传仓库ZIP<input type="file" accept=".zip" disabled={!!busy} onChange={e => { uploadRepo(e.target.files); e.target.value = ''; }}/></label></div>
        {project.repositories.length > 0 && <><label>选择仓库<select value={repoId} onChange={e => setRepoId(e.target.value)}><option value="">请选择</option>{project.repositories.map(r => <option value={r.id} key={r.id}>{r.name}</option>)}</select></label><label>Python入口<select value={entry} onChange={e => setEntry(e.target.value)}>{inspection?.entries.map((f: string) => <option key={f}>{f}</option>)}</select></label><label>运行名称<input value={config.name} onChange={e => setConfig({ ...config, name: e.target.value })}/></label><label>程序参数<textarea rows={3} value={args} onChange={e => setArgs(e.target.value)} placeholder={'每行一个参数，例如：\n--output\n/output'}/></label><details className="details"><summary>查看仓库README与依赖文件</summary><p className="caption">依赖文件：{inspection?.requirements.join('、') || '未找到'}</p><pre className="readme">{inspection?.readme}</pre></details></>}
        <div className="runtime-notice"><span className={'status-dot ' + (!status.docker ? 'offline' : '')}/><p>{!status.docker ? '启动Docker后即可运行外部仓库。' : status.image_ready ? '隔离环境就绪。仓库只读，结果写入/output；运行时不连接网络。' : 'Docker已启动，需要先准备隔离运行环境。'}<small>默认包含numpy、scikit-learn、matplotlib。其他依赖需加入运行镜像。</small></p>{status.docker && !status.image_ready && <button className="text-button" disabled={!!busy} onClick={() => action('runtime', async () => { await post('/runtime/prepare'); await refreshStatus(); }, '隔离运行环境已准备')}>{busy === 'runtime' ? '准备中…' : '准备环境'}</button>}</div>
      </>}
      <div className="run-action"><label>运行时限（秒）<input type="number" min="10" max="1800" value={config.timeout} onChange={e => setConfig({ ...config, timeout: Number(e.target.value) })}/></label><button className="button primary" disabled={!!busy || !config.name.trim() || (recipe === 'repository' && (!entry || !status.image_ready))} onClick={start}>{busy === 'run' ? <LoaderCircle size={16} className="spin"/> : <Play size={16}/>}开始真实运行</button></div>
    </section><div className="support-column"><section className="surface"><div className="section-heading"><h2>研究资料</h2><button className="text-button" onClick={goRead}>管理文献<ArrowUpRight size={15}/></button></div>{project.documents.length ? <div className="document-list">{project.documents.map(d => <button key={d.id} onClick={() => source(d.id)}><FileText size={19}/><span>{d.title}<small>{d.pages}页 · {d.spans.length}段可检索原文</small></span><ArrowRight size={15}/></button>)}</div> : <div className="empty compact"><FileText size={28}/><h3>为实验补上研究依据</h3><p>导入论文全文，或用示例说明体验资料到实验的流程。</p><div className="inline-actions"><button className="button secondary" onClick={goRead}>导入论文</button><button className="text-button" disabled={!!busy} onClick={() => action('demo', () => post(`/projects/${project.id}/demo`), '示例研究说明已载入')}>载入示例说明</button></div></div>}</section>
      <section className="surface"><div className="section-heading"><h2>执行计划</h2><button className="text-button" disabled={!!busy || !project.question.trim()} onClick={() => action('plan', async () => setPlan(await post(`/projects/${project.id}/plan`, { question: project.question })))}>{busy === 'plan' ? '整理中…' : '整理计划'}<ArrowRight size={15}/></button></div>{plan ? <><ol className="plan-list">{plan.steps?.map((s: any, i: number) => <li key={i}><b>{s.title}</b><p>{s.detail}</p></li>)}</ol>{plan.unknowns?.length > 0 && <div className="note">待确认：{plan.unknowns.join('；')}</div>}</> : <div className="empty-text"><p>计划从明确的研究问题开始。</p><span>填写上方问题后，可整理资料依据、运行安排与待确认条件。</span></div>}</section>
      <section className="scope-note"><CircleHelp size={19}/><div><b>运行成功，只是验证的起点</b><p>继续核对数据划分、参数和评价口径。缩减规模的运行不等同于完整复现。</p></div></section>
    </div></div> : <>
      <div className="results-grid"><section className="surface run-list"><div className="section-heading"><h2>运行记录</h2><button className="text-button" onClick={() => setTab('setup')}><Plus size={15}/>新实验</button></div>{project.runs.length ? project.runs.map(r => <div key={r.id} className={'run-item ' + (current?.id === r.id ? 'selected' : '')}><input type="checkbox" aria-label={`将${r.name}加入比较`} checked={comparison.includes(r.id)} onChange={e => setComparison(e.target.checked ? [...comparison, r.id] : comparison.filter(id => id !== r.id))}/><button onClick={() => { setSelectedRun(r.id); setDiagnosis(null); }}><b>{r.name}</b><span className={'badge ' + r.status}>{statuses[r.status]}</span><small>{date(r.created)} · {r.config.recipe === 'iris' ? 'Iris示例' : r.config.recipe === 'analysis' ? '数据分析' : '隔离仓库'}</small></button></div>) : <div className="empty compact"><FlaskConical size={32}/><h3>尚未运行实验</h3><p>配置并运行后，这里会保留真实日志、设定与结果。</p><button className="button secondary" onClick={() => setTab('setup')}>配置第一次实验</button></div>}</section>
      <section className="surface run-detail">{current && runDetail ? <><div className="section-heading"><div><h2>{current.name}</h2><p className="caption">{date(current.created)} · {statuses[current.status]}</p></div>{['running', 'queued'].includes(current.status) && <button className="button secondary" onClick={() => action('cancel', () => post(`/projects/${project.id}/runs/${current.id}/cancel`))}><Square size={14}/>停止</button>}</div>
        {Object.keys(current.metrics).length > 0 && <div className="metric-row">{Object.entries(current.metrics).map(([key, value]) => <div key={key}><span>{key}</span><b>{Number.isInteger(value) ? value : value.toFixed(4)}</b></div>)}</div>}
        <div className="log-heading"><span><Terminal size={15}/>实际运行日志</span>{['queued', 'running'].includes(current.status) && <span className="running-indicator"><span className="status-dot"/>实时更新</span>}</div><pre className="log">{runDetail.log || '等待实验进程输出…'}</pre>
        {current.status !== 'running' && <button className="text-button" disabled={!!busy} onClick={() => action('diagnose', async () => setDiagnosis(await post(`/projects/${project.id}/runs/${current.id}/diagnose`)))}><CircleHelp size={15}/>{busy === 'diagnose' ? '分析中…' : '分析运行状态'}</button>}
        {diagnosis && <div className="note diagnosis"><b>{diagnosis.cause}</b><ul>{diagnosis.suggestions?.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul></div>}
        {current.artifacts.length > 0 && <><h3 className="subheading">成果文件</h3><div className="artifact-links">{current.artifacts.map(f => <a key={f} href={`/api/projects/${project.id}/runs/${current.id}/artifacts/${f}`} download><FileText size={16}/>{f}<Download size={14}/></a>)}</div>{current.artifacts.includes('confusion.png') && <img className="plot" src={`/api/projects/${project.id}/runs/${current.id}/artifacts/confusion.png`} alt="本次真实实验的混淆矩阵"/>}</>}
      </> : <div className="empty"><Terminal size={32}/><h3>结果从实际运行开始</h3><p>选择左侧运行记录，查看日志、指标与成果文件。</p></div>}</section></div>
      <section className="surface compare-section"><div className="section-heading"><h2>比较实验结果</h2><span className="caption">勾选运行记录进行比较 · 未取得的指标保持为空</span></div>{comparison.length ? <div className="table-scroll"><table><thead><tr><th>运行</th><th>特征标准化</th><th>随机种子</th>{metricKeys.map(key => <th key={key}>{key}</th>)}</tr></thead><tbody>{compareRuns.map(r => <tr key={r.id}><td>{r.name}<small>{statuses[r.status]}</small></td><td>{r.config.recipe === 'iris' ? (r.config.standardize ? '启用' : '关闭') : '—'}</td><td>{r.config.recipe === 'iris' ? r.config.seed : '—'}</td>{metricKeys.map(key => <td key={key}>{r.metrics[key] === undefined ? '—' : Number.isInteger(r.metrics[key]) ? r.metrics[key] : r.metrics[key].toFixed(4)}</td>)}</tr>)}</tbody></table></div> : <p className="empty-text">勾选两条运行，比较原方案与变体的实际设定和结果。</p>}</section>
    </>}
  </>;
}

function Read({ project, busy, action, source, modelConfigured, settings }: SharedProps & { modelConfigured: boolean; settings: () => void }) {
  const [tab, setTab] = useState<'library' | 'matrix' | 'evidence' | 'reading' | 'structure' | 'compare' | 'agent'>('library');
  const [readingDocument, setReadingDocument] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [ask, setAsk] = useState(project.question);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [editing, setEditing] = useState('');
  const [draft, setDraft] = useState<Record<string, string>>({});
  const upload = (files: FileList | null) => {
    if (!files?.length) return;
    action('upload', async () => { for (const file of Array.from(files)) { const body = new FormData(); body.append('file', file); await api(`/projects/${project.id}/${file.name.toLowerCase().endsWith('.pdf') ? 'document-ingestions' : 'documents'}`, { method: 'POST', body }); } }, '文件已接收；PDF后台解析进度见文档结构');
  };
  const cite = (citation: string) => { const separator = citation.indexOf(':'); source(citation.slice(0, separator), citation.slice(separator + 1)); };
  return <>
    <div className="page-heading"><div><h1>文献与开题</h1><p>阅读原文、比较方法，为你的研究问题整理证据。</p></div><a className="button secondary" href={`/api/projects/${project.id}/export/proposal.md`}><Download size={16}/>导出开题准备材料</a></div>
    <ProjectQuestion project={project} action={action}/>
    <div className="tabs"><button className={tab === 'library' ? 'selected' : ''} onClick={() => setTab('library')}>文献库<span className="count">{project.documents.length}</span></button><button className={tab === 'matrix' ? 'selected' : ''} onClick={() => setTab('matrix')}>文献比较</button><button className={tab === 'evidence' ? 'selected' : ''} onClick={() => setTab('evidence')}>问题与证据</button><button className={tab === 'reading' ? 'selected' : ''} onClick={() => setTab('reading')}>论文精读</button><button className={tab === 'structure' ? 'selected' : ''} onClick={() => setTab('structure')}>文档结构</button><button className={tab === 'compare' ? 'selected' : ''} onClick={() => setTab('compare')}>证据比较</button><button className={tab === 'agent' ? 'selected' : ''} onClick={() => setTab('agent')}>研究任务</button></div>
    {tab === 'structure' && <Suspense fallback={<p role="status">正在打开文档结构…</p>}><DocumentStructure project={project} busy={busy} action={action} source={source}/></Suspense>}
    {(tab === 'compare' || tab === 'agent') && <Suspense fallback={<p role="status">正在打开证据工作区…</p>}><EvidenceTasks key={tab} kind={tab === 'agent' ? 'agent' : 'comparison'} project={project} busy={busy} action={action} source={source} modelConfigured={modelConfigured} settings={settings}/></Suspense>}
    {tab === 'reading' && <Suspense fallback={<div className="page-loading"><LoaderCircle className="spin"/>正在打开精读工作区…</div>}><PaperReader project={project} busy={busy} action={action} source={source} initialDocument={readingDocument} modelConfigured={modelConfigured} settings={settings}/></Suspense>}
    {tab === 'library' && <div className="library-grid"><section className="surface"><div className="section-heading"><h2>项目文献</h2><label className="button secondary file-button"><Upload size={15}/>{busy === 'upload' ? '导入中…' : '导入全文'}<input type="file" multiple accept=".pdf,.txt,.md" disabled={!!busy} onChange={e => { upload(e.target.files); e.target.value = ''; }}/></label></div>
      {project.documents.length ? <div className="library-list">{project.documents.map(d => <article key={d.id}><button className="document-title" onClick={() => source(d.id)}><span className="file-icon"><FileText size={23}/></span><span><b>{d.title}</b><small>{d.filename} · {d.pages}页 · {d.span_count ?? d.spans.length}段原文{d.ingestion && d.ingestion.status !== 'completed' ? ` · 解析${d.ingestion.completed}/${d.pages}页` : ''}</small></span></button><button className="button secondary read-document" onClick={() => { setReadingDocument(d.id); setTab('reading'); }}><BookOpen size={15}/>精读</button><button className="icon-button" title="移除资料" aria-label={`移除${d.title}`} disabled={!!busy} onClick={() => action('delete', () => api(`/projects/${project.id}/documents/${d.id}`, { method: 'DELETE' }), '资料已从项目移除')}><Trash2 size={16}/></button></article>)}</div> : <div className="empty upload-empty"><Library size={36}/><h3>从第一篇研究资料开始</h3><p>导入PDF、Markdown或文本，保留可回看的原文与页码。</p><label className="button primary file-button"><Upload size={16}/>选择文件<input type="file" multiple accept=".pdf,.txt,.md" disabled={!!busy} onChange={e => { upload(e.target.files); e.target.value = ''; }}/></label><span className="caption">每篇最大20MB · PDF后台解析与本机OCR</span><button className="text-button" disabled={!!busy} onClick={() => action('demo', () => post(`/projects/${project.id}/demo`), '示例研究说明已载入')}>先用示例资料体验<ArrowRight size={14}/></button></div>}
      <div className="surface-foot"><BookOpen size={16}/><span>项目文献同时可用于研复中的执行计划。</span></div>
    </section><section className="surface search-surface"><div className="section-heading"><h2>检索相关文献</h2><span className="badge neutral">Crossref</span></div><p className="muted">查找题名、作者与DOI。检索结果是题录，需另行取得并导入全文。</p><form onSubmit={e => { e.preventDefault(); action('search', async () => setResults(await api('/literature/search?q=' + encodeURIComponent(query)))); }}><div className="input-action"><input aria-label="文献关键词" value={query} onChange={e => setQuery(e.target.value)} placeholder="研究关键词或论文题名" required minLength={2}/><button className="button primary" disabled={!!busy} aria-label="检索文献">{busy === 'search' ? <LoaderCircle className="spin" size={17}/> : <Search size={17}/>}</button></div></form>{results.length ? <div className="search-results">{results.map((r, i) => <article key={i}><a href={r.url} target="_blank" rel="noreferrer">{r.title}<ExternalLink size={13}/></a><p>{r.authors}</p><small>{r.year || '年份未提供'} · {r.doi}</small></article>)}</div> : <div className="empty-text"><p>先用与你的问题直接相关的关键词检索。</p><span>题录不会自动计入全文证据。</span></div>}</section></div>}
    {tab === 'matrix' && <section className="surface"><div className="section-heading"><div><h2>把文献放在同一张表中</h2><p className="caption">提取条目保留原文定位；“未找到”不代表该论文没有对应内容。</p></div><div className="inline-actions"><a className="button secondary" href={`/api/projects/${project.id}/export/matrix.csv`}><Download size={15}/>CSV</a><button className="button primary" disabled={!!busy || !project.documents.length} onClick={() => action('matrix', () => post(`/projects/${project.id}/matrix`), '比较条目已整理，请逐项核对原文')}>{busy === 'matrix' ? <LoaderCircle className="spin" size={16}/> : <Layers size={16}/>}整理比较条目</button></div></div>
      {project.documents.length ? <div className="table-scroll matrix-scroll"><table className="matrix-table"><thead><tr><th>文献与核对状态</th>{fields.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{project.documents.map(d => <tr key={d.id}><td><button className="text-button doc-link" onClick={() => source(d.id)}>{d.title}</button><span className={'badge ' + (d.matrix.reviewed ? 'succeeded' : 'neutral')}>{d.matrix.reviewed ? '已人工核对' : d.matrix.mode === 'model' ? '模型提取 · 待核对' : d.matrix.mode === 'rule' ? '规则提取 · 待核对' : '尚未整理'}</span>{editing === d.id ? <div className="inline-actions"><button className="text-button" onClick={() => action('edit', async () => { await api(`/projects/${project.id}/documents/${d.id}/matrix`, { method: 'PUT', body: JSON.stringify(draft) }); setEditing(''); }, '修订已保存')}>保存核对</button><button className="text-button muted" onClick={() => setEditing('')}>取消</button></div> : <button className="text-button" onClick={() => { setEditing(d.id); setDraft(Object.fromEntries(fields.map(([key]) => [key, d.matrix[key]?.text || '未找到']))); }}><Pencil size={13}/>修订并核对</button>}</td>{fields.map(([key]) => { const field = d.matrix[key] as MatrixField | undefined; return <td key={key}>{editing === d.id ? <textarea aria-label={`${d.title}的${key}`} rows={7} value={draft[key] || ''} onChange={e => setDraft({ ...draft, [key]: e.target.value })}/> : <><p>{field?.text || '尚未整理'}</p>{field?.span_id && <button className="source-link" onClick={() => source(d.id, field.span_id!)}><BookOpen size={12}/>查看原文</button>}</>}</td>; })}</tr>)}</tbody></table></div> : <div className="empty"><Layers size={34}/><h3>先导入需要比较的文献</h3><p>可以从方法、数据、指标与局限四个维度开始。</p><button className="button secondary" onClick={() => setTab('library')}>返回文献库</button></div>}
    </section>}
    {tab === 'evidence' && <div className="evidence-grid"><section className="surface"><div className="section-heading"><h2>向项目资料提问</h2><BookOpen size={18} className="muted"/></div><form onSubmit={e => { e.preventDefault(); action('evidence', async () => setAnswer(await post(`/projects/${project.id}/evidence`, { question: ask }))); }}><label>你想核对的问题<textarea rows={4} value={ask} onChange={e => setAsk(e.target.value)} placeholder="例如：资料使用了什么数据划分和评价指标？" required minLength={2}/></label><div className="ask-action"><span className="caption">仅检索当前项目已导入的全文</span><button className="button primary" disabled={!!busy || !project.documents.length}>{busy === 'evidence' ? <LoaderCircle className="spin" size={16}/> : <Search size={16}/>}查找证据</button></div></form>
      {answer ? <div className="answer"><span className="badge neutral">{answer.mode === 'model' ? '模型整理 · 引用可回看' : '原文检索'}</span><p>{answer.answer}</p>{answer.claims.map((claim, i) => <div className="claim" key={i}><p>{claim.text}</p><div>{claim.citations.map((c, j) => <button className="source-link" key={c} onClick={() => cite(c)}><BookOpen size={12}/>依据{j + 1}</button>)}</div></div>)}</div> : <div className="empty-text"><p>问题越具体，证据越容易核对。</p><span>未配置模型时显示检索原文；配置后可生成带引用的综合说明。</span></div>}</section>
      <section className="surface"><div className="section-heading"><h2>原文证据</h2><span className="caption">{answer?.evidence.length || 0}段</span></div>{answer?.evidence.length ? <div className="evidence-list">{answer.evidence.map((p, i) => <article key={p.citation}><div><span className="evidence-number">{i + 1}</span><button onClick={() => source(p.document_id, p.id)}>{p.title}<small>第{p.page}页 · {p.id}</small></button></div><p>{p.text}</p><button className="source-link" onClick={() => source(p.document_id, p.id)}>打开全文位置<ArrowUpRight size={12}/></button></article>)}</div> : <div className="empty compact"><BookOpen size={30}/><h3>每一段证据都可以回看</h3><p>提问后，这里显示检索到的原文和页码。</p></div>}</section>
    </div>}
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
