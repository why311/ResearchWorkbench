import { useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, CircleHelp, Download, FileText, FlaskConical, GitBranch, LoaderCircle, Play, Plus, Square, Terminal, Upload } from 'lucide-react';
import { api, post, type ExperimentProps, type Run } from './api';

type SharedProps = ExperimentProps & { source: (did: string) => void };
type Status = { docker: boolean; image_ready: boolean };
const statuses: Record<string, string> = { queued: '等待运行', running: '运行中', succeeded: '已完成', failed: '运行失败', timeout: '已超时', cancelled: '已取消', interrupted: '运行中断' };
const date = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

export default function Reproduce({ project, busy, action, status, refreshStatus, source, goRead, initialRun }: SharedProps & { status: Status; refreshStatus: () => Promise<void>; goRead: () => void; initialRun: string }) {
  const [tab, setTab] = useState<'setup' | 'results'>(initialRun ? 'results' : 'setup');
  const [recipe, setRecipe] = useState('iris');
  const [config, setConfig] = useState({ name: '标准化特征 · 原方案', standardize: true, regularization: 1, test_size: 0.3, seed: 42, max_iter: 200, timeout: 120 });
  const [repoUrl, setRepoUrl] = useState('');
  const [repoId, setRepoId] = useState(project.repositories[0]?.id || '');
  const [entry, setEntry] = useState('');
  const [args, setArgs] = useState('');
  const [inspection, setInspection] = useState<any>(null);
  const [selectedRun, setSelectedRun] = useState(initialRun);
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
    const file = files?.[0];
    if (!file) return;
    action('repo', async () => { const body = new FormData(); body.append('file', file); const repo = await api(`/projects/${project.id}/repositories/upload`, { method: 'POST', body }); setRepoId(repo.id); }, '仓库已导入，尚未执行代码');
  };
  const start = () => action('run', async () => {
    const result = await post(`/projects/${project.id}/runs`, { ...config, recipe, repository_id: repoId, entry, args: args.split('\n').map(a => a.trim()).filter(Boolean) });
    setSelectedRun(result.id); setRunDetail(null); setTab('results'); setDiagnosis(null);
  }, '实验已提交，结果由实际运行产生');
  const compareRuns = project.runs.filter(r => comparison.includes(r.id));
  const metricKeys = [...new Set(compareRuns.flatMap(r => Object.keys(r.metrics)))];
  return <>
    <div className="page-heading"><div><h1>实验复现</h1></div><a className="button secondary" href={`/api/projects/${project.id}/export/reproduction.zip`}><Download size={16}/>导出复现材料</a></div>
    <div className="tabs"><button className={tab === 'setup' ? 'selected' : ''} onClick={() => setTab('setup')}>实验准备</button><button className={tab === 'results' ? 'selected' : ''} onClick={() => setTab('results')}>运行记录<span className="count">{project.runs.length}</span></button></div>
    {tab === 'setup' ? <div className="reproduce-grid"><section className="surface config-surface"><div className="section-heading"><h2>配置一次实验</h2></div>
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
    </section><div className="support-column"><section className="surface"><div className="section-heading"><h2>研究资料</h2><button className="text-button" onClick={goRead}>管理文献<ArrowUpRight size={15}/></button></div>{project.documents.length ? <div className="document-list">{project.documents.map(d => <button key={d.id} onClick={() => source(d.id)}><FileText size={19}/><span>{d.title}<small>{d.pages}页 · {d.span_count || 0}段可检索原文</small></span><ArrowRight size={15}/></button>)}</div> : <div className="empty compact"><FileText size={28}/><h3>为实验补上研究依据</h3><p>导入论文全文。</p><div className="inline-actions"><button className="button secondary" onClick={goRead}>导入论文</button></div></div>}</section>
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
