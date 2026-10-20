import { useEffect, useState } from 'react';
import { ArrowRight, BookOpen, Check, Download, FileText, LoaderCircle, Play, Square, Upload, X } from 'lucide-react';
import { api, post, type ModuleProps, type Ingestion, type ResearchTask, type SourcePage } from './api';
import './library.css';

const stateText: Record<string, string> = { queued: '等待执行', running: '执行中', completed: '已完成', failed: '执行失败', cancelled: '已停止', interrupted: '已中断' };
const cellText: Record<string, string> = { quote_checked: '引文已核对 · 解释待审阅', evidence_only: '仅定位原文', not_found: '本次检索未找到', unverified: '模型提取待核对' };
const toolText: Record<string, string> = { inspect_documents: '检查文献范围', search_evidence: '检索原文证据', compare_papers: '逐篇比较与引文核对', prepare_reproduction: '整理复现条件', finish: '汇总工具结果' };
type Props = ModuleProps & { source: (did: string, sid?: string) => void };

export function DocumentStructure({ project, busy, action, source }: Props) {
  const [jobs, setJobs] = useState<Ingestion[]>([]);
  const [id, setId] = useState(project.documents[0]?.id || '');
  const doc = project.documents.find(d => d.id === id) || project.documents[0];
  const [page, setPage] = useState(1);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<SourcePage | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [highlight, setHighlight] = useState('');
  const [imageError, setImageError] = useState(false);
  useEffect(() => { setPage(1); setOffset(0); setHighlight(''); setImageError(false); }, [doc?.id]);
  useEffect(() => { setOffset(0); setImageError(false); }, [page]);
  useEffect(() => {
    let live = true;
    const load = () => api(`/projects/${project.id}/document-ingestions`).then(v => { if (live) setJobs(v); }).catch(e => { if (live) setError(e.message); });
    load(); const timer = window.setInterval(load, 2000);
    return () => { live = false; clearInterval(timer); };
  }, [project.id, reload]);
  useEffect(() => {
    let live = true;
    setData(null); setError('');
    if (doc) api(`/projects/${project.id}/documents/${doc.id}/spans?page=${page}&offset=${offset}`).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [project.id, doc?.id, page, offset, doc?.ingestion?.completed, reload]);
  const upload = (files: FileList | null) => {
    if (!files?.length) return;
    action('structured-upload', async () => {
      for (const file of Array.from(files)) {
        const body = new FormData(); body.append('file', file);
        const job = await api(`/projects/${project.id}/document-ingestions`, { method: 'POST', body });
        setJobs(old => [job, ...old]); setId(job.document_id);
      }
      setReload(v => v + 1);
    }, 'PDF已接收，后台逐页解析；原文件保留');
  };
  const selected = data?.items.find(s => s.id === highlight);
  const profile = doc?.ingestion?.profile;
  return <div className="structured-library">
    <div className="section-heading"><div><h2>文档结构与原页</h2><p className="caption">原文件留存，按页加载。标题为候选识别；扫描页在本机OCR，不发送给外部模型。</p></div><label className="button primary file-button"><Upload size={15}/>解析PDF<input aria-label="结构化导入PDF" type="file" multiple accept=".pdf" disabled={!!busy} onChange={e => { upload(e.target.files); e.target.value = ''; }}/></label></div>
    <p className="caption parse-budget">每篇20MB、最多2000页；最多2个解析进程。单页90秒、总计20分钟、进程内存1GB、正文400万字符；超限保留已完成页并说明原因。</p>
    {jobs.length > 0 && <div className="parse-jobs" aria-label="PDF解析任务">{jobs.slice(0, 8).map(job => <article key={job.id}><button className="text-button" onClick={() => setId(job.document_id)}>{project.documents.find(d => d.id === job.document_id)?.title || '新导入PDF'}</button><span className={'badge ' + (job.status === 'completed' ? 'succeeded' : 'neutral')}>{stateText[job.status]}</span><span>{job.completed}/{job.total}页</span><progress max={job.total} value={job.completed} aria-label={`解析进度${job.document_id}`}/>{['queued', 'running'].includes(job.status) ? <button className="text-button" disabled={!!busy} onClick={() => action('stop-parse', async () => { await post(`/projects/${project.id}/document-ingestions/${job.id}/cancel`); setReload(v => v + 1); })}><Square size={13}/>停止</button> : ['failed', 'cancelled', 'interrupted'].includes(job.status) && <button className="text-button" disabled={!!busy} onClick={() => action('resume-parse', async () => { await post(`/projects/${project.id}/document-ingestions/${job.id}/resume`); setReload(v => v + 1); })}><Play size={13}/>继续解析</button>}{job.error && <p role="status">{job.error}</p>}</article>)}</div>}
    {error && <div className="feedback error" role="alert"><span>{error}</span><button onClick={() => setReload(v => v + 1)}>重新加载</button></div>}
    {!doc ? <div className="empty"><FileText size={32}/><h3>从原文建立可核对的文献库</h3><p>导入PDF，查看标题导航、文字坐标、原页、表格和OCR结果。</p></div> : <>
      <div className="document-controls"><label>当前文献<select aria-label="结构文献" value={doc.id} onChange={e => setId(e.target.value)}>{project.documents.map(d => <option value={d.id} key={d.id}>{d.title}</option>)}</select></label><label>查看页码<input aria-label="文档结构页码" type="number" min={1} max={doc.pages} value={page} onChange={e => { const p = Number(e.target.value); if (Number.isInteger(p) && p >= 1 && p <= doc.pages) setPage(p); }}/></label><span>/ {doc.pages}页</span>{doc.has_original && <a className="button secondary" target="_blank" rel="noreferrer" href={`/api/projects/${project.id}/documents/${doc.id}/original`}>打开原文件</a>}</div>
      {!!profile?.duplicates?.length && <div className="duplicate-notice"><h3>发现可能的同篇文献或修订版</h3>{profile.duplicates.map(d => <p key={d.document_id}><button className="text-button" onClick={() => source(d.document_id)}>{d.title}</button> · 内容相似度 {d.similarity.toFixed(3)}。{d.suggestion}<small>{d.scope}</small></p>)}<p>文件均已保留，不自动覆盖已有引用。</p></div>}
      <div className="document-layout"><aside className="document-toc"><h3>候选标题导航</h3>{profile?.headings?.length ? profile.headings.map(h => <button key={h.span_id} style={{ paddingLeft: 10 + (h.level - 1) * 10 }} className={page === h.page ? 'selected' : ''} onClick={() => { setPage(h.page); setHighlight(h.span_id); }}>{h.text}<small>第{h.page}页</small></button>) : <p className="caption">解析完成后显示识别到的标题；未识别的内容仍可按页阅读。</p>}<p className="caption">{profile?.doi && <>DOI：{profile.doi}<br/></>}{profile?.arxiv && <>arXiv：{profile.arxiv}{profile.version ? 'v' + profile.version : ''}<br/></>}{profile?.author && <>文档作者元数据：{profile.author}</>}</p></aside>
        <section className="document-page"><div className="section-heading"><h3>第{page}页原貌</h3><span className="caption">{data?.details?.method === 'ocr' ? '本机OCR · 需核对' : data?.details ? `原生文字 · ${data.details.columns}栏候选` : '原文件页面'}</span></div>{doc.has_original && doc.filename.toLowerCase().endsWith('.pdf') ? imageError ? <p role="alert">原页暂时无法渲染，请打开原文件查看。</p> : <div className="document-page-image"><img loading="lazy" src={`/api/projects/${project.id}/documents/${doc.id}/page-image/${page}`} alt={`${doc.title}第${page}页原文`} onError={() => setImageError(true)}/>{selected?.bbox && data?.details && <span className="page-highlight" style={{ left: selected.bbox[0] / data.details.width * 100 + '%', top: selected.bbox[1] / data.details.height * 100 + '%', width: (selected.bbox[2] - selected.bbox[0]) / data.details.width * 100 + '%', height: (selected.bbox[3] - selected.bbox[1]) / data.details.height * 100 + '%' }}/>}</div> : <p className="empty-text">这份旧资料未保存PDF原文件，可查看已提取文字。</p>}</section>
        <section className="document-blocks"><div className="section-heading"><h3>本页结构与文字</h3><span className="caption">{data?.total || 0}段</span></div>{!data && !error && <p role="status"><LoaderCircle size={16} className="spin"/>正在读取当前页…</p>}{data && !data.items.length && <p className="empty-text">本页尚未解析或未识别到文字，请查看原页及任务状态。</p>}{data?.items.map(span => <article key={span.id} className={highlight === span.id ? 'selected' : ''}><div><button className="text-button" onClick={() => setHighlight(span.id)}>{span.kind === 'heading' ? '候选标题' : '原文'} · {span.id}</button>{span.confidence !== undefined && <small>OCR置信度 {span.confidence.toFixed(2)}</small>}</div><p>{span.text}</p>{span.formula_candidate && <p className="caption">包含公式候选文字，请对照原页；尚未转换为可信LaTeX。</p>}<button className="text-button" onClick={() => source(doc.id, span.id)}><BookOpen size={13}/>回看与核对原文</button></article>)}{data?.details?.tables.map((table, i) => <details key={i}><summary>线框表格 {i + 1} · {table.rows.length}行</summary><div className="table-scroll"><table>{table.rows.slice(0, 20).map((row, r) => <tbody key={r}><tr>{row.map((cell, c) => <td key={c}>{cell}</td>)}</tr></tbody>)}</table></div><p className="caption">预览前20行，识别可能存在跨单元格错误，需对照原页。</p></details>)}{data?.details && <p className="caption">本页{data.details.figures.length}个图像区域、{data.details.tables.length}个线框表格。扫描图表尚未还原为结构化数据。</p>}<div className="inline-actions"><button className="button secondary" disabled={page <= 1 && !offset} onClick={() => offset ? setOffset(Math.max(0, offset - 200)) : setPage(p => p - 1)}>上一页段</button><button className="button secondary" disabled={!data || page >= doc.pages && !data.has_more} onClick={() => data?.has_more ? setOffset(n => n + 200) : setPage(p => p + 1)}>下一页段<ArrowRight size={14}/></button></div></section>
      </div>
    </>}
  </div>;
}

export function EvidenceTasks({ project, busy, action, source, kind, modelConfigured, settings }: Props & { kind: 'comparison' | 'agent'; modelConfigured: boolean; settings: () => void }) {
  const [selection, setSelection] = useState(project.documents.slice(0, 3).map(d => d.id));
  const [fields, setFields] = useState('研究方法\n数据集与划分\n随机种子\n超参数与训练设置\n硬件环境\n评价指标');
  const [intent, setIntent] = useState(project.question || '比较这些论文的实验设定，找出复现前需要确认的条件');
  const [tasks, setTasks] = useState<ResearchTask[]>([]);
  const [id, setId] = useState('');
  const [task, setTask] = useState<ResearchTask | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    const load = () => api(`/projects/${project.id}/research-tasks`).then(v => { if (live) setTasks(v); }).catch(e => { if (live) setError(e.message); });
    load(); const timer = setInterval(load, 2200);
    return () => { live = false; clearInterval(timer); };
  }, [project.id, reload]);
  const tid = id || tasks.find(t => t.kind === kind)?.id || '';
  useEffect(() => {
    let live = true;
    const load = () => { if (tid) api(`/projects/${project.id}/research-tasks/${tid}`).then(v => { if (live) { setTask(v); setError(''); } }).catch(e => { if (live) setError(e.message); }); };
    setTask(null); load(); const timer = setInterval(load, 1800);
    return () => { live = false; clearInterval(timer); };
  }, [project.id, tid, reload]);
  const active = task && ['queued', 'running'].includes(task.status);
  const fieldList = fields.split('\n').map(s => s.trim()).filter(Boolean);
  const create = () => action('research-task-create', async () => {
    const data = await post(`/projects/${project.id}/research-tasks`, { kind, intent, document_ids: selection, fields: fieldList });
    setId(data.id); setTask(data); setReload(v => v + 1);
  }, '任务已创建，工具执行与来源记录会逐步显示');
  const comparison = task?.result?.comparison;
  const createNote = () => action('task-note', async () => {
    await post(`/projects/${project.id}/research-tasks/${task!.id}/research-note`);
    setTask(await api(`/projects/${project.id}/research-tasks/${task!.id}`));
  }, '已保存为待验证研究设想，可到总览继续设计实验');
  return <div className="evidence-workspace"><section className="task-composer"><h2>{kind === 'agent' ? '给研究任务一个明确目标' : '逐项比较，逐条回到原文'}</h2><p className="caption">{kind === 'agent' ? '配置模型后由Function Calling选择工具，最多6步；没有模型时执行明确标注的本地流程。' : '对每篇文献分别检索，避免只从一篇论文中找到证据。引文可核对，解释仍需判断。'}</p><label>任务目标<textarea aria-label="研究任务目标" rows={3} maxLength={2000} value={intent} onChange={e => setIntent(e.target.value)}/></label><fieldset><legend>选择文献（1—8篇）</legend>{project.documents.map(doc => <label className="task-document-choice" key={doc.id}><input type="checkbox" checked={selection.includes(doc.id)} disabled={!selection.includes(doc.id) && selection.length >= 8} onChange={e => setSelection(old => e.target.checked ? [...old, doc.id] : old.filter(id => id !== doc.id))}/><span>{doc.title}<small>{doc.ingestion ? `已解析${doc.ingestion.completed}/${doc.pages}页` : `${doc.pages}页`}</small></span></label>)}{!project.documents.length && <p className="empty-text">先从文献库导入全文。</p>}</fieldset><label>比较项（每行一项，最多8项）<textarea aria-label="研究比较项" rows={6} value={fields} onChange={e => setFields(e.target.value)}/></label><p className="caption">{modelConfigured ? '任务目标、所选文献元数据和检索到的原文会发送至已配置的模型服务。' : '当前无模型配置：可实际检索原文和生成核对清单，不自动提取值或综合结论。'}</p><div className="note-actions"><button className="button primary" disabled={!!busy || !!active || !selection.length || !intent.trim() || fieldList.length < 1 || fieldList.length > 8 || fieldList.some(f => f.length > 100)} onClick={create}><Play size={15}/>{kind === 'agent' ? '开始研究任务' : '开始证据比较'}</button>{!modelConfigured && <button className="text-button" onClick={settings}>配置模型服务</button>}</div></section>
    <section className="task-results"><div className="section-heading"><h2>{kind === 'agent' ? '工具执行与研究记录' : '证据比较记录'}</h2>{task && <span className={'badge ' + (task.status === 'completed' ? 'succeeded' : 'neutral')}>{stateText[task.status]}</span>}</div><label>查看已保存任务<select aria-label="已保存研究任务" value={tid} onChange={e => setId(e.target.value)}><option value="">选择任务</option>{tasks.filter(t => t.kind === kind).map(t => <option key={t.id} value={t.id}>{t.intent.slice(0, 45)} · {stateText[t.status]}</option>)}</select></label>{error && <div role="alert" className="feedback error"><span>{error}</span><button className="text-button" onClick={() => setReload(v => v + 1)}>重试</button></div>}{task ? <><div className="task-record-heading"><div><h3>{task.intent}</h3><p className="caption">{task.mode === 'function_calling' ? '模型自主选择工具 · 实际Function Calling' : '本地流程 · 非模型自主规划'} · {task.steps.length}/6步</p></div>{active && <button className="button secondary" disabled={!!busy} onClick={() => action('task-stop', async () => { setTask(await post(`/projects/${project.id}/research-tasks/${task.id}/cancel`)); })}><Square size={14}/>停止任务</button>}</div>{task.error && <p className="reading-warning" role="status">{task.error}</p>}<ol className="tool-timeline">{task.steps.map((step, i) => <li key={i} className={step.status}><div><span>{step.status === 'running' ? <LoaderCircle size={15} className="spin"/> : step.status === 'failed' ? <X size={15}/> : <Check size={15}/>}</span><b>{toolText[step.tool] || step.tool}</b><small>{stateText[step.status]}</small></div>{step.progress && <p>{step.progress}</p>}<details><summary>工具参数与实际返回</summary><pre>{JSON.stringify({ arguments: step.arguments, output: step.output }, null, 2)}</pre></details></li>)}</ol>{!task.steps.length && <p className="empty-text" role="status">任务等待开始，执行后会显示实际工具记录。</p>}{comparison && <><div className="comparison-heading"><h3>逐篇证据比较</h3><a className="text-button" href={`/api/projects/${project.id}/research-tasks/${task.id}/export?format=csv`}><Download size={14}/>比较表CSV</a></div><div className="comparison-table-scroll"><table className="grounded-comparison"><thead><tr><th>核对项</th>{comparison.rows.map(r => <th key={r.document_id}>{r.title}<small>{r.scope}</small></th>)}</tr></thead><tbody>{comparison.fields.map(field => <tr key={field}><th scope="row">{field}</th>{comparison.rows.map(row => { const cell = row.cells.find(c => c.field === field)!; return <td key={row.document_id}><span className={'cell-state ' + cell.status}>{cellText[cell.status]}</span><p>{cell.value}</p>{cell.evidence.map(e => <details key={e.citation}><summary>第{e.page}页 · {e.id}</summary><blockquote>{e.quote || e.text}</blockquote><button className="text-button" onClick={() => source(e.document_id, e.id)}><BookOpen size={13}/>回看原文</button></details>)}</td>; })}</tr>)}</tbody></table></div><p className="caption">{comparison.retrieval}</p><p className="caption">{comparison.limitation}</p>{comparison.warnings.map(w => <p className="reading-warning" key={w}>{w}</p>)}</>}{task.result?.checklist && <div className="reproduction-checklist"><h3>复现前需要核对</h3>{task.result.checklist.map(row => <article key={row.document_id}><h4>{row.title}</h4><p>{row.conditions.filter((c: any) => c.status !== 'quote_checked').map((c: any) => c.field).join('、') || '已定位各项引文，仍需人工核对解释与适用条件。'}</p><p className="caption">{row.next}</p></article>)}</div>}{task.result?.claims?.map((c, i) => <article className="task-claim" key={i}><p>{c.text}</p><blockquote>{c.quote}</blockquote><button className="text-button" onClick={() => source(c.source.document_id, c.source.id)}>核对来源 · 第{c.source.page}页</button></article>)}{task.result?.note && <p className="task-outcome">{task.result.note}</p>}<div className="note-actions"><a className="button secondary" href={`/api/projects/${project.id}/research-tasks/${task.id}/export`}><Download size={15}/>导出完整工具记录</a>{comparison && !active && <button className="button secondary" disabled={!!busy || !!task.result.note_id} onClick={createNote}><BookOpen size={15}/>{task.result.note_id ? '已保存为待验证设想' : '保存为待验证设想'}</button>}</div></> : !error && <div className="empty"><BookOpen size={32}/><h3>从一个可回答的问题开始</h3><p>选择资料和比较项，系统会实际检索、记录依据，并保留尚未确认的内容。</p></div>}</section>
  </div>;
}
