import { useState, useEffect } from 'react';
import { BookOpen, ChartNoAxesCombined, Check, Download, FileText, LoaderCircle, Plus, RefreshCw, Trash2, Workflow } from 'lucide-react';
import { api, post, type DeliveryProps, type Report, type ReportForm, type Binding } from './api';
import ReportCitations from './ReportCitations';

const syncNames: Record<string, string> = { new: '尚未生成', synced: '已同步', stale: '需要更新', invalid: '引用待修复' };
const format = (value: number | null | undefined, precision = 4) => value === undefined || value === null ? '—' : Number.isInteger(value) ? String(value) : value.toFixed(precision);
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

export function SyncModule({ project, busy, action, source, drafts }: DeliveryProps & {
  source: (did: string, sid?: string) => void;
  drafts: { id: string; title: string }[];
}) {
  const reports = project.reports || [];
  const successful = project.runs.filter(r => r.status === 'succeeded' && Object.keys(r.metrics).length);
  const blank = (): ReportForm => ({ title: (project.name + ' · 成果记录').slice(0, 100), template: '## 研究结果\n\n在这里填写正文，并通过下方按钮插入绑定真实结果的变量。\n\n## 解释与局限\n\n请结合实验设定与证据说明结果，避免仅凭数值变化判断显著性或因果。', bindings: [], citations: [], chart_run_ids: [], chart_metrics: [] });
  const [selectedId, setSelectedId] = useState('');
  const [draftId, setDraftId] = useState('');
  const importDraft = () => action('import-draft', async () => {
    const report = await post(`/projects/${project.id}/reports/from-draft`, { draft_id: draftId });
    setSelectedId(report.id);
    setDraftId('');
  }, '已从写作草稿创建成果文稿');
  const [form, setForm] = useState<ReportForm>(blank);
  const [record, setRecord] = useState<Report | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [wordTemplate, setWordTemplate] = useState('generic');
  const [citationCheck, setCitationCheck] = useState<any>(null);
  useEffect(() => { let active = true; if (selectedId) api(`/projects/${project.id}/reports/${selectedId}`).then(data => { if (active) { setRecord(data); setCitationCheck(null); setForm({ title: data.title, template: data.template, bindings: data.bindings, citations: data.citations || [], chart_run_ids: data.chart_run_ids, chart_metrics: data.chart_metrics }); } }).catch(() => {}); return () => { active = false; }; }, [selectedId, project.id]);
  const refreshReport = () => action('source-check', async () => { if (selectedId) setRecord(await api(`/projects/${project.id}/reports/${selectedId}`)); }, '来源与更新状态已检查');
  const save = async () => {
    const data = await api(`/projects/${project.id}/reports${selectedId ? '/' + selectedId : ''}`, { method: selectedId ? 'PUT' : 'POST', body: JSON.stringify(form) });
    setSelectedId(data.id); setRecord(data); return data as Report;
  };
  const downloadWord = () => action('export-word', async () => {
    if (!record?.generated.id) return;
    const response = await fetch(`/api/projects/${project.id}/reports/${record.id}/word?template=${wordTemplate}`);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Word导出失败，请检查正文与公式后重试');
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = `research-report-v${record.generated.version}.docx`;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'Word已按当前生成版本导出，包含正文、指标、图表及来源说明');
  const generate = () => action('generate-report', async () => { const saved = await save(); const data = await post(`/projects/${project.id}/reports/${saved.id}/generate`); setRecord(data); }, '成果已按当前真实来源生成');
  const sourceMetric = (binding: Binding) => successful.find(r => r.id === binding.run_id)?.metrics[binding.metric];
  const citationOrder = [...new Set([...form.template.matchAll(/\[\[cite:([A-Za-z][A-Za-z0-9_]{0,39})\]\]/g)].map(m => m[1]))];
  const preview = form.template.replace(/\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}/g, (_, alias) => {
    const binding = form.bindings.find(b => b.alias === alias); if (!binding) return '(未绑定)';
    const value = sourceMetric(binding); if (value === undefined) return '(引用失效)';
    return binding.display === 'percent' ? (value * 100).toFixed(binding.precision) + '%' : value.toFixed(binding.precision);
  }).replace(/\[\[cite:([A-Za-z][A-Za-z0-9_]{0,39})\]\]/g, (_, alias) => form.citations.some(c => c.alias === alias) ? `[${citationOrder.indexOf(alias) + 1}]` : '(文献引用未绑定)');
  const editBinding = (index: number, patch: Partial<Binding>) => setForm(p => ({ ...p, bindings: p.bindings.map((b, i) => i === index ? { ...b, ...patch } : b) }));
  const availableMetrics = [...new Set(successful.filter(r => form.chart_run_ids.includes(r.id)).flatMap(r => Object.keys(r.metrics)))];
  const chooseChartRun = (rid: string) => setForm(p => {
    const ids = p.chart_run_ids.includes(rid) ? p.chart_run_ids.filter(id => id !== rid) : [...p.chart_run_ids, rid];
    const keys = new Set(successful.filter(r => ids.includes(r.id)).flatMap(r => Object.keys(r.metrics)));
    return { ...p, chart_run_ids: ids, chart_metrics: p.chart_metrics.filter(m => keys.has(m)) };
  });
  const savedForm = record ? { title: record.title, template: record.template, bindings: record.bindings, citations: record.citations || [], chart_run_ids: record.chart_run_ids, chart_metrics: record.chart_metrics } : null;
  const dirty = !savedForm || JSON.stringify(savedForm) !== JSON.stringify(form);
  return <>
    <div className="page-heading"><div><h1>成果同步</h1></div><div className="inline-actions" style={{ flexWrap: 'wrap' }}>{record?.generated.id && <a className="button secondary" href={`/api/projects/${project.id}/reports/${record.id}/export`}><Download size={16}/>导出已生成成果</a>}{record?.generated.id && <button className="button secondary" disabled={!!busy} onClick={downloadWord}>{busy === 'export-word' ? <LoaderCircle size={16} className="spin"/> : <FileText size={16}/>}导出Word · 第{record.generated.version}版</button>}<label>Word格式<select aria-label="Word格式" value={wordTemplate} onChange={e => setWordTemplate(e.target.value)}><option value="generic">通用成果</option><option value="school">本机论文模板</option></select></label><button className="button primary" disabled={!!busy || !form.title.trim()} onClick={generate}>{busy === 'generate-report' ? <LoaderCircle size={16} className="spin"/> : <Workflow size={16}/>}生成并同步</button></div></div>
    {drafts.length > 0 && <div className="page-actions">
      <label>写作草稿<select disabled={!!busy} value={draftId} onChange={event => setDraftId(event.target.value)}>
        <option value="">选择写作草稿</option>
        {drafts.map(draft => <option key={draft.id} value={draft.id}>{draft.title}</option>)}
      </select></label>
      <button disabled={!!busy || !draftId} onClick={importDraft}>转为成果文稿</button>
    </div>}
    <div className="report-toolbar"><div><label>成果文稿<select aria-label="成果文稿" value={selectedId} onChange={e => { setSelectedId(e.target.value); if (!e.target.value) { setForm(blank()); setRecord(null); } }}><option value="">新建成果文稿</option>{reports.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label><button className="icon-button" aria-label="新建成果文稿" onClick={() => { setSelectedId(''); setRecord(null); setForm(blank()); }}><Plus size={18}/></button></div><span className={'badge ' + (dirty ? 'neutral' : record?.sync_status === 'synced' ? 'succeeded' : 'pending')}>{dirty ? '修改尚未保存' : syncNames[record?.sync_status || 'new']}</span>{record && <button className="text-button" disabled={!!busy} onClick={refreshReport}>检查来源<RefreshCw size={14}/></button>}</div>
    {record && !dirty && (record.sync_status === 'stale' || record.sync_status === 'invalid') && <div className="note changes-note"><b>{record.sync_status === 'invalid' ? '有引用需要修复' : '文稿或结果来源已变化，上次生成的成果尚未更新'}</b>{record.changes.map(c => <p key={c.alias}>{c.alias}：{c.before} → {c.after}{c.source_changed ? '（来源运行已更换）' : ''}</p>)}{record.errors.map(e => <p key={e}>{e}</p>)}</div>}
    <div className="studio-grid sync-grid"><section className="surface"><div className="section-heading"><h2>文稿与结果引用</h2><button className="text-button" disabled={!!busy || !form.title.trim()} onClick={() => action('save-report', save, '成果草稿已保存')}>保存草稿<Check size={14}/></button></div><label className="first-label">成果标题<input value={form.title} maxLength={100} onChange={e => setForm({ ...form, title: e.target.value })}/></label><label>正文（Markdown）<textarea aria-label="正文（Markdown）" className="manuscript-editor" rows={9} value={form.template} maxLength={30000} onChange={e => setForm({ ...form, template: e.target.value })}/></label>
      <div className="section-heading bindings-heading"><h3>绑定真实指标</h3><button className="text-button" disabled={!successful.length || form.bindings.length >= 30} onClick={() => { const first = successful[0]; let n = form.bindings.length + 1; while (form.bindings.some(b => b.alias === `result_${n}`)) n++; setForm({ ...form, bindings: [...form.bindings, { alias: `result_${n}`, run_id: first.id, metric: Object.keys(first.metrics)[0], precision: 4, display: 'number' }] }); }}><Plus size={14}/>添加指标引用</button></div>
      {form.bindings.map((binding, i) => { const run = successful.find(r => r.id === binding.run_id); return <div className="binding-row" key={i}><div className="binding-top"><label>变量名<input aria-label={`变量${i + 1}名称`} value={binding.alias} maxLength={40} onChange={e => editBinding(i, { alias: e.target.value })}/></label><button className="icon-button" aria-label={`删除变量${i + 1}`} onClick={() => setForm({ ...form, bindings: form.bindings.filter((_, j) => i !== j) })}><Trash2 size={15}/></button></div><label>来源运行<select aria-label={`变量${i + 1}来源`} value={binding.run_id} onChange={e => { const r = successful.find(r => r.id === e.target.value)!; editBinding(i, { run_id: r.id, metric: binding.metric in r.metrics ? binding.metric : Object.keys(r.metrics)[0] }); }}>{successful.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label><div className="form-grid"><label>指标<select aria-label={`变量${i + 1}指标`} value={binding.metric} onChange={e => editBinding(i, { metric: e.target.value })}>{Object.keys(run?.metrics || {}).map(k => <option key={k}>{k}</option>)}</select></label><label>显示方式<select aria-label={`变量${i + 1}显示方式`} value={binding.display} onChange={e => editBinding(i, { display: e.target.value as Binding['display'] })}><option value="number">数值</option><option value="percent">百分比</option></select></label><label>小数位<input aria-label={`变量${i + 1}小数位`} type="number" min="0" max="8" step="1" value={binding.precision} onChange={e => editBinding(i, { precision: Math.max(0, Math.min(8, Math.trunc(Number(e.target.value) || 0))) })}/></label><div className="binding-value"><span>真实值</span><b>{format(sourceMetric(binding))}</b></div></div><button className="text-button" onClick={() => setForm({ ...form, template: form.template + ` {{${binding.alias}}}` })}>插入引用<Plus size={13}/></button></div>; })}
      {!successful.length && <div className="empty-text"><p>当前项目没有成功完成的结果。</p><span>先在实验复现运行实验或在数据分析执行分析，再绑定真实指标。</span></div>}
      <ReportCitations project={project} source={source} citations={form.citations} template={form.template} disabled={!!busy} onChange={citations => setForm(p => ({ ...p, citations }))} onInsert={alias => setForm(p => ({ ...p, template: p.template + ` [[cite:${alias}]]` }))}/>
    </section><div className="support-column"><section className="surface"><div className="section-heading"><h2>文稿预览</h2></div><pre className="manuscript-preview">{preview}</pre><p className="caption">只更新绑定变量，不自动改写解释性结论。预览不代表成果文件已经更新。</p>{record && !dirty && form.citations.length>0 && <button className="button secondary" disabled={!!busy} onClick={()=>action('check-citations',async()=>setCitationCheck(await post(`/projects/${project.id}/reports/${record.id}/citation-check`)))}>核对引文支持</button>}{citationCheck && !dirty && <div>{citationCheck.stale && <p>文稿已修改，请重新核对引用。</p>}<p className="caption">{citationCheck.result.scope}</p>{citationCheck.result.checks.map((c:any)=><p key={c.alias}>{c.alias} · {({supported:'原文支持',partial:'部分支持',unsupported:'缺少支持',contradicted:'与原文冲突',unknown:'未核对'} as any)[c.verdict]}：{c.reason}</p>)}</div>}</section><section className="surface"><div className="section-heading"><h2>比较图表</h2><ChartNoAxesCombined size={18} className="muted"/></div><p className="caption">各指标单独作图，缺失值不补零。</p><div className="chart-sources">{successful.map(r => <label className="checkbox-row" key={r.id}><input type="checkbox" checked={form.chart_run_ids.includes(r.id)} onChange={() => chooseChartRun(r.id)}/><span>{r.name}<small>{r.config.recipe === 'analysis' ? '数据分析' : '实验运行'} · {time(r.created)}</small></span></label>)}</div>{availableMetrics.length > 0 && <div className="metric-checks">{availableMetrics.map(metric => <label className="checkbox-row" key={metric}><input type="checkbox" checked={form.chart_metrics.includes(metric)} onChange={e => setForm({ ...form, chart_metrics: e.target.checked ? [...form.chart_metrics, metric] : form.chart_metrics.filter(m => m !== metric) })}/><span>{metric}</span></label>)}</div>}</section>
      {record?.generated.id && <section className="surface"><div className="section-heading"><h2>已生成成果</h2><span className="caption">第{record.generated.version}版 · {time(record.generated.created!)}</span></div><div className="artifact-links">{record.generated.files?.map(f => <a key={f} href={`/api/projects/${project.id}/reports/${record.id}/artifacts/${f}?v=${record.generated.id}`} download><FileText size={14}/>{f}<Download size={13}/></a>)}</div>{record.generated.files?.includes('figure.png') && <img className="analysis-plot" src={`/api/projects/${project.id}/reports/${record.id}/artifacts/figure.png?v=${record.generated.id}`} alt="依据实际运行结果生成的比较图"/>}<button className="text-button" onClick={() => setSourcesOpen(!sourcesOpen)}><BookOpen size={14}/>{sourcesOpen ? '收起' : '查看'}来源说明</button>{sourcesOpen && <p className="caption">来源记录与文稿、图表一起保存在sources.json。Word使用本次生成版本的正文和数据；修改草稿或引用后需重新生成。支持标题、段落、列表、表格和可转换的LaTeX公式，外部图片不会自动嵌入。</p>}</section>}
    </div></div>
  </>;
}
