import { useEffect, useState } from 'react';
import { BookOpen, Check, Download, LoaderCircle, Play, Square, X } from 'lucide-react';
import { api, post, type ModuleProps, type ResearchTask } from './api';

const stateText: Record<string, string> = { queued: '等待执行', running: '执行中', completed: '已完成', failed: '执行失败', cancelled: '已停止', interrupted: '已中断' };
const cellText: Record<string, string> = { quote_checked: '引文已核对 · 解释待审阅', evidence_only: '仅定位原文', not_found: '本次检索未找到', unverified: '模型提取待核对' };
const toolText: Record<string, string> = { inspect_documents: '检查文献范围', search_evidence: '检索原文证据', compare_papers: '逐篇比较与引文核对', prepare_reproduction: '整理复现条件', finish: '汇总工具结果' };
type Props = ModuleProps & { source: (did: string, sid?: string) => void };

export function EvidenceTasks({ project, busy, action, source, kind, modelConfigured }: Props & { kind: 'comparison' | 'agent'; modelConfigured: boolean }) {
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
  }, '任务已创建');
  const comparison = task?.result?.comparison;
  const createNote = () => action('task-note', async () => {
    await post(`/projects/${project.id}/research-tasks/${task!.id}/research-note`);
    setTask(await api(`/projects/${project.id}/research-tasks/${task!.id}`));
  }, '已保存待验证设想');
  return <div className="evidence-workspace"><section className="task-composer"><h2>{kind === 'agent' ? '给研究任务一个明确目标' : '逐项比较，逐条回到原文'}</h2><p className="caption">{kind === 'agent' ? '配置模型后由Function Calling选择工具，最多6步；没有模型时执行明确标注的本地流程。' : '对每篇文献分别检索，避免只从一篇论文中找到证据。引文可核对，解释仍需判断。'}</p><label>任务目标<textarea aria-label="研究任务目标" rows={3} maxLength={2000} value={intent} onChange={e => setIntent(e.target.value)}/></label><fieldset><legend>选择文献（1—8篇）</legend>{project.documents.map(doc => <label className="task-document-choice" key={doc.id}><input type="checkbox" checked={selection.includes(doc.id)} disabled={!selection.includes(doc.id) && selection.length >= 8} onChange={e => setSelection(old => e.target.checked ? [...old, doc.id] : old.filter(id => id !== doc.id))}/><span>{doc.title}<small>{doc.ingestion ? `已解析${doc.ingestion.completed}/${doc.pages}页` : `${doc.pages}页`}</small></span></label>)}{!project.documents.length && <p className="empty-text">先从文献库导入全文。</p>}</fieldset><label>比较项（每行一项，最多8项）<textarea aria-label="研究比较项" rows={6} value={fields} onChange={e => setFields(e.target.value)}/></label><p className="caption">{modelConfigured ? '任务目标、所选文献元数据和检索到的原文会发送至已配置的模型服务。' : '当前无模型配置：可实际检索原文和生成核对清单，不自动提取值或综合结论。'}</p><div className="note-actions"><button className="button primary" disabled={!!busy || !!active || !selection.length || !intent.trim() || fieldList.length < 1 || fieldList.length > 8 || fieldList.some(f => f.length > 100)} onClick={create}><Play size={15}/>{kind === 'agent' ? '开始研究任务' : '开始证据比较'}</button></div></section>
    <section className="task-results"><div className="section-heading"><h2>{kind === 'agent' ? '工具执行与研究记录' : '证据比较记录'}</h2>{task && <span className={'badge ' + (task.status === 'completed' ? 'succeeded' : 'neutral')}>{stateText[task.status]}</span>}</div><label>查看已保存任务<select aria-label="已保存研究任务" value={tid} onChange={e => setId(e.target.value)}><option value="">选择任务</option>{tasks.filter(t => t.kind === kind).map(t => <option key={t.id} value={t.id}>{t.intent.slice(0, 45)} · {stateText[t.status]}</option>)}</select></label>{error && <div role="alert" className="feedback error"><span>{error}</span><button className="text-button" onClick={() => setReload(v => v + 1)}>重试</button></div>}{task ? <><div className="task-record-heading"><div><h3>{task.intent}</h3><p className="caption">{task.mode === 'function_calling' ? '模型自主选择工具 · 实际Function Calling' : '本地流程 · 非模型自主规划'} · {task.steps.length}/6步</p></div>{active && <button className="button secondary" disabled={!!busy} onClick={() => action('task-stop', async () => { setTask(await post(`/projects/${project.id}/research-tasks/${task.id}/cancel`)); })}><Square size={14}/>停止任务</button>}</div>{task.error && <p className="reading-warning" role="status">{task.error}</p>}<ol className="tool-timeline">{task.steps.map((step, i) => <li key={i} className={step.status}><div><span>{step.status === 'running' ? <LoaderCircle size={15} className="spin"/> : step.status === 'failed' ? <X size={15}/> : <Check size={15}/>}</span><b>{toolText[step.tool] || step.tool}</b><small>{stateText[step.status]}</small></div>{step.progress && <p>{step.progress}</p>}<details><summary>工具参数与实际返回</summary><pre>{JSON.stringify({ arguments: step.arguments, output: step.output }, null, 2)}</pre></details></li>)}</ol>{!task.steps.length && <p className="empty-text" role="status">任务等待开始，执行后会显示实际工具记录。</p>}{comparison && <><div className="comparison-heading"><h3>逐篇证据比较</h3><a className="text-button" href={`/api/projects/${project.id}/research-tasks/${task.id}/export?format=csv`}><Download size={14}/>比较表CSV</a></div><div className="comparison-table-scroll"><table className="grounded-comparison"><thead><tr><th>核对项</th>{comparison.rows.map(r => <th key={r.document_id}>{r.title}<small>{r.scope}</small></th>)}</tr></thead><tbody>{comparison.fields.map(field => <tr key={field}><th scope="row">{field}</th>{comparison.rows.map(row => { const cell = row.cells.find(c => c.field === field)!; return <td key={row.document_id}><span className={'cell-state ' + cell.status}>{cellText[cell.status]}</span><p>{cell.value}</p>{cell.evidence.map(e => <details key={e.citation}><summary>第{e.page}页 · {e.id}</summary><blockquote>{e.quote || e.text}</blockquote><button className="text-button" onClick={() => source(e.document_id, e.id)}><BookOpen size={13}/>回看原文</button></details>)}</td>; })}</tr>)}</tbody></table></div><p className="caption">{comparison.retrieval}</p><p className="caption">{comparison.limitation}</p>{comparison.warnings.map(w => <p className="reading-warning" key={w}>{w}</p>)}</>}{task.result?.checklist && <div className="reproduction-checklist"><h3>复现前需要核对</h3>{task.result.checklist.map(row => <article key={row.document_id}><h4>{row.title}</h4><p>{row.conditions.filter((c: any) => c.status !== 'quote_checked').map((c: any) => c.field).join('、') || '已定位各项引文，仍需人工核对解释与适用条件。'}</p><p className="caption">{row.next}</p></article>)}</div>}{task.result?.claims?.map((c, i) => <article className="task-claim" key={i}><p>{c.text}</p><blockquote>{c.quote}</blockquote><button className="text-button" onClick={() => source(c.source.document_id, c.source.id)}>核对来源 · 第{c.source.page}页</button></article>)}{task.result?.note && <p className="task-outcome">{task.result.note}</p>}<div className="note-actions"><a className="button secondary" href={`/api/projects/${project.id}/research-tasks/${task.id}/export`}><Download size={15}/>导出完整工具记录</a>{comparison && !active && <button className="button secondary" disabled={!!busy || !!task.result.note_id} onClick={createNote}><BookOpen size={15}/>{task.result.note_id ? '已保存为待验证设想' : '保存为待验证设想'}</button>}{task.result.note_id && <a className="button secondary" href={`/api/projects/${project.id}/research-notes/${task.result.note_id}/export`}>导出待验证设想</a>}</div></> : !error && <div className="empty"><BookOpen size={32}/><h3>从一个可回答的问题开始</h3><p>选择资料和比较项，系统会实际检索、记录依据，并保留尚未确认的内容。</p></div>}</section>
  </div>;
}
