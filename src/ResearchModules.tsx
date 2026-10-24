import { useState, useEffect, useRef } from 'react';
import { Upload, Download, Plus, FileText, Play, Layers, Check, Trash2, RefreshCw, BookOpen, ArrowRight, LoaderCircle, ChartNoAxesCombined, Workflow, Square, Pencil } from 'lucide-react';
import { api, post, type ModuleProps, type Dataset, type Run, type Report, type ReportForm, type Binding } from './api';

type Plan = { columns: string[]; missing: string; deduplicate: boolean; scales: Record<string, number>; filters: { column: string; minimum: number | null; maximum: number | null }[]; methods: string[]; group_by: string };
const statusNames: Record<string, string> = { queued: '等待运行', running: '运行中', succeeded: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断', timeout: '已超时' };
const syncNames: Record<string, string> = { new: '尚未生成', synced: '已同步', stale: '需要更新', invalid: '引用待修复' };
const format = (value: number | null | undefined, precision = 4) => value === undefined || value === null ? '—' : Number.isInteger(value) ? String(value) : value.toFixed(precision);
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const artifactUrl = (pid: string, rid: string, name: string) => `/api/projects/${pid}/runs/${rid}/artifacts/${name}`;

export function AnalysisModule({ project, busy, action }: ModuleProps) {
  const datasets = project.datasets || [];
  const [datasetId, setDatasetId] = useState(datasets[0]?.id || '');
  const selected = datasets.find(d => d.id === datasetId) || datasets[0];
  const [plan, setPlan] = useState<Plan>({ columns: [], missing: 'keep', deduplicate: false, scales: {}, filters: [], methods: ['summary'], group_by: '' });
  const [name, setName] = useState('描述统计与比较');
  const pendingPlan = useRef<{ id: string; plan: Plan } | null>(null);
  const [resultTab, setResultTab] = useState('summary');
  const [resultId, setResultId] = useState('');
  const [detail, setDetail] = useState<{ run: Run; result: any } | null>(null);
  const [importRun, setImportRun] = useState('');
  const runs = project.runs.filter(r => r.config.recipe === 'analysis');
  const current = runs.find(r => r.id === resultId) || runs[0];
  useEffect(() => {
    if (!selected) return;
    if (pendingPlan.current?.id === selected.id) { setPlan(pendingPlan.current.plan); pendingPlan.current = null; return; }
    setPlan({ columns: selected.profile.fields.filter(f => f.kind === 'numeric').slice(0, 4).map(f => f.name), missing: 'keep', deduplicate: false, scales: {}, filters: [], methods: ['summary'], group_by: '' });
  }, [selected?.id]);
  useEffect(() => {
    let active = true;
    if (current) api(`/projects/${project.id}/analysis/${current.id}`).then(data => { if (active) setDetail(data); }).catch(() => {});
    return () => { active = false; };
  }, [current?.id, current?.status, project.id, project.runs]);
  const load = (file: File | undefined) => { if (!file) return; action('dataset', async () => { const body = new FormData(); body.append('file', file); const d = await api(`/projects/${project.id}/datasets`, { method: 'POST', body }); setDatasetId(d.id); }, '数据已导入并完成字段检查'); };
  const run = () => action('analysis', async () => { const r = await post(`/projects/${project.id}/analysis`, { name, dataset_id: selected?.id, plan }); setResultId(r.id); setDetail(null); }, '分析已提交，结果由实际计算产生');
  const toggleColumn = (column: string) => setPlan(p => {
    const columns = p.columns.includes(column) ? p.columns.filter(c => c !== column) : [...p.columns, column];
    return { ...p, columns, scales: Object.fromEntries(Object.entries(p.scales).filter(([c]) => columns.includes(c))), filters: p.filters.filter(f => columns.includes(f.column)), group_by: columns.includes(p.group_by) ? '' : p.group_by };
  });
  const toggleMethod = (method: string) => setPlan(p => ({ ...p, methods: p.methods.includes(method) ? p.methods.filter(m => m !== method) : [...p.methods, method] }));
  const result = detail?.result;
  const resultMatches = detail?.run.id === current?.id;
  const csvRuns = project.runs.filter(r => r.status === 'succeeded' && r.artifacts.some(f => /\.(csv|tsv)$/i.test(f)));
  const selectedImport = csvRuns.find(r => r.id === importRun) || csvRuns[0];
  return <>
    <div className="page-heading"><div><h1>数据分析</h1><p>确认处理计划，实际计算，并保留能够复跑的过程。</p></div><label className="button secondary file-button"><Upload size={16}/>{busy === 'dataset' ? '导入中…' : '导入数据'}<input type="file" accept=".csv,.tsv,.xlsx" disabled={!!busy} onChange={e => { load(e.target.files?.[0]); e.target.value = ''; }}/></label></div>
    <div className="studio-grid"><section className="surface data-input"><div className="section-heading"><h2>数据与处理计划</h2><span className="caption">CSV · TSV · Excel</span></div>
      {selected ? <><label className="first-label">当前数据<select aria-label="当前数据" value={selected.id} onChange={e => setDatasetId(e.target.value)}>{datasets.map(d => <option key={d.id} value={d.id}>{d.name} · {d.row_count}行</option>)}</select></label>
        <div className="dataset-facts"><span>{selected.row_count}行 / {selected.columns.length}列</span><span>{selected.profile.duplicates}行完全重复</span><span>{selected.profile.encoding}</span></div>
        {selected.profile.source === 'demo' && <p className="note">{selected.profile.description}</p>}{selected.profile.sheet && <p className="caption">Excel读取首张工作表：{selected.profile.sheet}（文件共有{selected.profile.sheet_count}张表）。</p>}{selected.profile.source_run_name && <p className="caption">来自真实运行：{selected.profile.source_run_name}</p>}
        <label>分析名称<input value={name} maxLength={100} onChange={e => setName(e.target.value)}/></label>
        <h3 className="subheading">选择数值分析字段</h3><div className="field-checks">{selected.profile.fields.map(f => <label key={f.name} className="field-check"><input type="checkbox" checked={plan.columns.includes(f.name)} onChange={() => toggleColumn(f.name)}/><span><b>{f.name}</b><small>{f.kind === 'numeric' ? '数值' : f.kind === 'mixed' ? '混合类型' : '文本'} · 缺失{f.missing} · 可解析数值{f.numeric_count}</small></span></label>)}</div>
        <label>缺失值处理<select aria-label="缺失值处理" value={plan.missing} onChange={e => setPlan({ ...plan, missing: e.target.value })}><option value="keep">保留缺失，按有效值计算</option><option value="drop">删除所选字段或分组字段缺失的行</option><option value="median">用每个数值字段的中位数填补</option></select></label>
        <label className="checkbox-row"><input type="checkbox" checked={plan.deduplicate} onChange={e => setPlan({ ...plan, deduplicate: e.target.checked })}/><span>去除完全重复的行<small>比较原始数据的全部字段，不自动删除异常值</small></span></label>
        <details className="details transform-details"><summary>单位换算与范围筛选</summary><p className="caption">处理顺序：去重 → 数值解析与换算 → 范围筛选 → 缺失处理。筛选使用换算后的值。</p>{plan.columns.map(column => {
          const condition = plan.filters.find(f => f.column === column);
          const changeBound = (key: 'minimum' | 'maximum', raw: string) => { const next = { column, minimum: condition?.minimum ?? null, maximum: condition?.maximum ?? null, [key]: raw === '' ? null : Number(raw) }; setPlan({ ...plan, filters: [...plan.filters.filter(f => f.column !== column), ...(next.minimum === null && next.maximum === null ? [] : [next])] }); };
          return <div className="transform-row" key={column}><b>{column}</b><label>乘以<input aria-label={`${column}换算系数`} type="number" step="any" value={plan.scales[column] ?? 1} onChange={e => setPlan({ ...plan, scales: { ...plan.scales, [column]: Number(e.target.value) } })}/></label><label>下限<input aria-label={`${column}筛选下限`} type="number" step="any" value={condition?.minimum ?? ''} placeholder="不限" onChange={e => changeBound('minimum', e.target.value)}/></label><label>上限<input aria-label={`${column}筛选上限`} type="number" step="any" value={condition?.maximum ?? ''} placeholder="不限" onChange={e => changeBound('maximum', e.target.value)}/></label></div>;
        })}</details>
        <h3 className="subheading">计算内容</h3><div className="method-checks"><span className="badge neutral">描述统计始终提供</span><label className="checkbox-row"><input type="checkbox" checked={plan.methods.includes('groups')} onChange={() => toggleMethod('groups')}/><span>分组描述比较</span></label>{plan.methods.includes('groups') && <label>分组字段<select aria-label="分组字段" value={plan.group_by} onChange={e => setPlan({ ...plan, group_by: e.target.value })}><option value="">请选择分类字段</option>{selected.columns.filter(c => !plan.columns.includes(c)).map(c => <option key={c}>{c}</option>)}</select></label>}<label className="checkbox-row"><input type="checkbox" checked={plan.methods.includes('correlation')} onChange={() => toggleMethod('correlation')}/><span>Pearson相关分析<small>至少两个数值字段；不据此判断因果或显著性</small></span></label></div>
        <div className="analysis-start"><span className="caption">非数值内容记为缺失并记录数量</span><button className="button primary" disabled={!!busy || !name.trim() || !plan.columns.length || (plan.methods.includes('groups') && !plan.group_by) || (plan.methods.includes('correlation') && plan.columns.length < 2)} onClick={run}>{busy === 'analysis' ? <LoaderCircle className="spin" size={16}/> : <Play size={16}/>}执行分析</button></div>
      </> : <div className="empty compact"><ChartNoAxesCombined size={32}/><h3>从真实数据开始</h3><p>第一行作为字段名。Excel读取首张工作表，公式需先转为数值。</p><label className="button primary file-button"><Upload size={16}/>选择数据文件<input type="file" accept=".csv,.tsv,.xlsx" disabled={!!busy} onChange={e => { load(e.target.files?.[0]); e.target.value = ''; }}/></label><button className="text-button" disabled={!!busy} onClick={() => action('data-demo', async () => { const d = await post(`/projects/${project.id}/datasets/demo`); setDatasetId(d.id); }, '人工示例数据已载入')}>载入流程示例<ArrowRight size={14}/></button></div>}
      {csvRuns.length > 0 && <details className="details import-results"><summary>从实验记录导入结果表</summary><select aria-label="选择结果来源运行" value={selectedImport?.id || ''} onChange={e => setImportRun(e.target.value)}>{csvRuns.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select><div className="artifact-links">{selectedImport?.artifacts.filter(f => /\.(csv|tsv)$/i.test(f)).map(f => <button className="text-button" key={f} disabled={!!busy} onClick={() => action('data-import', async () => { const d = await post(`/projects/${project.id}/datasets/from-run`, { run_id: selectedImport.id, filename: f }); setDatasetId(d.id); }, '实验结果表已导入')}>{f}<Plus size={13}/></button>)}</div></details>}
    </section><div className="support-column analysis-output"><section className="surface"><div className="section-heading"><h2>数据预览</h2><span className="caption">原始值 · 前15行</span></div>{selected ? <div className="table-scroll preview-table"><table><thead><tr>{selected.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{selected.profile.preview.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{v || <span className="muted">缺失</span>}</td>)}</tr>)}</tbody></table></div> : <p className="empty-text">上传数据后，可核对字段、缺失情况与原始内容。</p>}</section>
      <section className="surface"><div className="section-heading"><h2>分析结果</h2>{current && <span className={'badge ' + current.status}>{statusNames[current.status]}</span>}</div>{runs.length > 0 && <label className="first-label">查看已保存的分析<select aria-label="查看已保存的分析" value={current?.id || ''} onChange={e => { setResultId(e.target.value); setDetail(null); }}>{runs.map(r => <option key={r.id} value={r.id}>{r.name} · {statusNames[r.status]}</option>)}</select></label>}
        {current ? <><div className="result-meta"><span>来源：{current.config.dataset_name}</span><span>{time(current.created)}</span></div><div className="inline-actions result-actions"><button className="text-button" onClick={() => { pendingPlan.current = current.config.dataset_id === selected?.id ? null : { id: current.config.dataset_id, plan: current.config.plan }; setDatasetId(current.config.dataset_id); setPlan(current.config.plan); setName(current.name.slice(0, 85) + ' · 复跑'); }}>载入此处理计划<RefreshCw size={14}/></button>{current.status === 'succeeded' && <a className="button secondary" href={`/api/projects/${project.id}/analysis/${current.id}/export`}><Download size={14}/>导出复跑包</a>}{['running', 'queued'].includes(current.status) && <button className="text-button" onClick={() => action('stop', () => post(`/projects/${project.id}/runs/${current.id}/cancel`))}><Square size={13}/>停止</button>}</div>
          {resultMatches && result ? <><div className="audit-line">输入{result.audit.input_rows}行 → 输出{result.audit.output_rows}行<span>去重{result.audit.duplicates_removed} / 筛除{result.audit.filtered_rows} / 缺失删行{result.audit.missing_rows_removed} / 填补{result.audit.imputed_cells} / 无效数值{result.audit.invalid_cells}</span></div><div className="tabs mini-tabs">{[['summary', '统计'], ['groups', '分组'], ['correlations', '相关'], ['files', '图表与文件']].map(([key, label]) => <button key={key} className={resultTab === key ? 'selected' : ''} onClick={() => setResultTab(key)}>{label}</button>)}</div>
            {resultTab === 'summary' && <StatsTable rows={result.summary}/>}{resultTab === 'groups' && (result.groups.length ? <StatsTable rows={result.groups} group/> : <p className="empty-text">此运行未选择分组比较。</p>)}{resultTab === 'correlations' && (result.correlations.length ? <div className="table-scroll"><table><thead><tr><th>字段X</th><th>字段Y</th><th>有效对数</th><th>Pearson r</th></tr></thead><tbody>{result.correlations.map((r: any, i: number) => <tr key={i}><td>{r.x}</td><td>{r.y}</td><td>{r.n}</td><td>{format(r.pearson_r)}</td></tr>)}</tbody></table></div> : <p className="empty-text">此运行未选择相关分析。</p>)}{resultTab === 'files' && <><div className="artifact-links">{current.artifacts.map(f => <a key={f} href={artifactUrl(project.id, current.id, f)} download><FileText size={14}/>{f}<Download size={13}/></a>)}</div>{current.artifacts.filter(f => f.endsWith('.png')).map(f => <img key={f} className="analysis-plot" src={artifactUrl(project.id, current.id, f)} alt={`实际分析图表 ${f}`}/>)}</>}
            <details className="details"><summary>计算口径与实际日志</summary><ul className="analysis-notes">{result.notes.map((note: string) => <li key={note}>{note}</li>)}</ul><pre className="log">{detail?.run.log}</pre></details>
          </> : <div className="analysis-pending">{['running', 'queued'].includes(current.status) ? <p><LoaderCircle className="spin" size={17}/>正在实际执行分析…</p> : <p>未生成成功结果，请查看日志。</p>}<pre className="log">{resultMatches ? detail?.run.log || '等待进程输出…' : '读取运行记录…'}</pre></div>}
        </> : <div className="empty compact"><Play size={27}/><h3>结果由实际执行产生</h3><p>确认左侧处理计划后开始分析，统计、图表和复跑代码会一起保存。</p></div>}
      </section></div></div>
  </>;
}

function StatsTable({ rows, group = false }: { rows: any[]; group?: boolean }) {
  return <div className="table-scroll"><table className="stats-table"><thead><tr>{group && <th>分组</th>}<th>字段</th><th>有效n</th><th>缺失</th><th>均值</th><th>中位数</th><th>样本标准差</th><th>最小值</th><th>最大值</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{group && <td>{r.group}</td>}<td>{r.column}</td>{['count', 'missing', 'mean', 'median', 'std', 'min', 'max'].map(k => <td key={k}>{format(r[k])}</td>)}</tr>)}</tbody></table></div>;
}

export function SyncModule({ project, busy, action }: ModuleProps) {
  const reports = project.reports || [];
  const successful = project.runs.filter(r => r.status === 'succeeded' && Object.keys(r.metrics).length);
  const blank = (): ReportForm => ({ title: project.name + ' · 成果记录', template: '## 研究结果\n\n在这里填写正文，并通过下方按钮插入绑定真实结果的变量。\n\n## 解释与局限\n\n请结合实验设定与证据说明结果，避免仅凭数值变化判断显著性或因果。', bindings: [], chart_run_ids: [], chart_metrics: [] });
  const [selectedId, setSelectedId] = useState('');
  const [form, setForm] = useState<ReportForm>(blank);
  const [record, setRecord] = useState<Report | null>(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  useEffect(() => { let active = true; if (selectedId) api(`/projects/${project.id}/reports/${selectedId}`).then(data => { if (active) { setRecord(data); setForm({ title: data.title, template: data.template, bindings: data.bindings, chart_run_ids: data.chart_run_ids, chart_metrics: data.chart_metrics }); } }).catch(() => {}); return () => { active = false; }; }, [selectedId, project.id]);
  const refreshReport = () => action('source-check', async () => { if (selectedId) setRecord(await api(`/projects/${project.id}/reports/${selectedId}`)); }, '来源与更新状态已检查');
  const save = async () => {
    const data = await api(`/projects/${project.id}/reports${selectedId ? '/' + selectedId : ''}`, { method: selectedId ? 'PUT' : 'POST', body: JSON.stringify(form) });
    setSelectedId(data.id); setRecord(data); return data as Report;
  };
  const downloadWord = () => action('export-word', async () => {
    if (!record?.generated.id) return;
    const response = await fetch(`/api/projects/${project.id}/reports/${record.id}/word`);
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
  const preview = form.template.replace(/\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}/g, (_, alias) => {
    const binding = form.bindings.find(b => b.alias === alias); if (!binding) return '(未绑定)';
    const value = sourceMetric(binding); if (value === undefined) return '(引用失效)';
    return binding.display === 'percent' ? (value * 100).toFixed(binding.precision) + '%' : value.toFixed(binding.precision);
  });
  const editBinding = (index: number, patch: Partial<Binding>) => setForm(p => ({ ...p, bindings: p.bindings.map((b, i) => i === index ? { ...b, ...patch } : b) }));
  const availableMetrics = [...new Set(successful.filter(r => form.chart_run_ids.includes(r.id)).flatMap(r => Object.keys(r.metrics)))];
  const chooseChartRun = (rid: string) => setForm(p => {
    const ids = p.chart_run_ids.includes(rid) ? p.chart_run_ids.filter(id => id !== rid) : [...p.chart_run_ids, rid];
    const keys = new Set(successful.filter(r => ids.includes(r.id)).flatMap(r => Object.keys(r.metrics)));
    return { ...p, chart_run_ids: ids, chart_metrics: p.chart_metrics.filter(m => keys.has(m)) };
  });
  const savedForm = record ? { title: record.title, template: record.template, bindings: record.bindings, chart_run_ids: record.chart_run_ids, chart_metrics: record.chart_metrics } : null;
  const dirty = !savedForm || JSON.stringify(savedForm) !== JSON.stringify(form);
  return <>
    <div className="page-heading"><div><h1>成果同步</h1><p>把真实实验和分析结果，连接到图表与文稿中的引用。</p></div><div className="inline-actions">{record?.generated.id && <a className="button secondary" href={`/api/projects/${project.id}/reports/${record.id}/export`}><Download size={16}/>导出已生成成果</a>}{record?.generated.id && <button className="button secondary" disabled={!!busy} onClick={downloadWord}>{busy === 'export-word' ? <LoaderCircle size={16} className="spin"/> : <FileText size={16}/>}导出Word · 第{record.generated.version}版</button>}<button className="button primary" disabled={!!busy || !form.title.trim()} onClick={generate}>{busy === 'generate-report' ? <LoaderCircle size={16} className="spin"/> : <Workflow size={16}/>}生成并同步</button></div></div>
    <div className="report-toolbar"><div><label>成果文稿<select aria-label="成果文稿" value={selectedId} onChange={e => { setSelectedId(e.target.value); if (!e.target.value) { setForm(blank()); setRecord(null); } }}><option value="">新建成果文稿</option>{reports.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label><button className="icon-button" aria-label="新建成果文稿" onClick={() => { setSelectedId(''); setRecord(null); setForm(blank()); }}><Plus size={18}/></button></div><span className={'badge ' + (dirty ? 'neutral' : record?.sync_status === 'synced' ? 'succeeded' : 'pending')}>{dirty ? '修改尚未保存' : syncNames[record?.sync_status || 'new']}</span>{record && <button className="text-button" disabled={!!busy} onClick={refreshReport}>检查来源<RefreshCw size={14}/></button>}</div>
    {record && !dirty && (record.sync_status === 'stale' || record.sync_status === 'invalid') && <div className="note changes-note"><b>{record.sync_status === 'invalid' ? '有引用需要修复' : '文稿或结果来源已变化，上次生成的成果尚未更新'}</b>{record.changes.map(c => <p key={c.alias}>{c.alias}：{c.before} → {c.after}{c.source_changed ? '（来源运行已更换）' : ''}</p>)}{record.errors.map(e => <p key={e}>{e}</p>)}</div>}
    <div className="studio-grid sync-grid"><section className="surface"><div className="section-heading"><h2>文稿与结果引用</h2><button className="text-button" disabled={!!busy || !form.title.trim()} onClick={() => action('save-report', save, '成果草稿已保存')}>保存草稿<Check size={14}/></button></div><label className="first-label">成果标题<input value={form.title} maxLength={100} onChange={e => setForm({ ...form, title: e.target.value })}/></label><label>正文（Markdown）<textarea aria-label="正文（Markdown）" className="manuscript-editor" rows={9} value={form.template} maxLength={30000} onChange={e => setForm({ ...form, template: e.target.value })}/></label><p className="caption">变量形式为双花括号包住变量名。点击“插入引用”即可添加，生成时取对应运行的真实值。</p>
      <div className="section-heading bindings-heading"><h3>绑定真实指标</h3><button className="text-button" disabled={!successful.length || form.bindings.length >= 30} onClick={() => { const first = successful[0]; let n = form.bindings.length + 1; while (form.bindings.some(b => b.alias === `result_${n}`)) n++; setForm({ ...form, bindings: [...form.bindings, { alias: `result_${n}`, run_id: first.id, metric: Object.keys(first.metrics)[0], precision: 4, display: 'number' }] }); }}><Plus size={14}/>添加指标引用</button></div>
      {form.bindings.map((binding, i) => { const run = successful.find(r => r.id === binding.run_id); return <div className="binding-row" key={i}><div className="binding-top"><label>变量名<input aria-label={`变量${i + 1}名称`} value={binding.alias} maxLength={40} onChange={e => editBinding(i, { alias: e.target.value })}/></label><button className="icon-button" aria-label={`删除变量${i + 1}`} onClick={() => setForm({ ...form, bindings: form.bindings.filter((_, j) => i !== j) })}><Trash2 size={15}/></button></div><label>来源运行<select aria-label={`变量${i + 1}来源`} value={binding.run_id} onChange={e => { const r = successful.find(r => r.id === e.target.value)!; editBinding(i, { run_id: r.id, metric: binding.metric in r.metrics ? binding.metric : Object.keys(r.metrics)[0] }); }}>{successful.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label><div className="form-grid"><label>指标<select aria-label={`变量${i + 1}指标`} value={binding.metric} onChange={e => editBinding(i, { metric: e.target.value })}>{Object.keys(run?.metrics || {}).map(k => <option key={k}>{k}</option>)}</select></label><label>显示方式<select aria-label={`变量${i + 1}显示方式`} value={binding.display} onChange={e => editBinding(i, { display: e.target.value as Binding['display'] })}><option value="number">数值</option><option value="percent">百分比</option></select></label><label>小数位<input aria-label={`变量${i + 1}小数位`} type="number" min="0" max="8" step="1" value={binding.precision} onChange={e => editBinding(i, { precision: Math.max(0, Math.min(8, Math.trunc(Number(e.target.value) || 0))) })}/></label><div className="binding-value"><span>真实值</span><b>{format(sourceMetric(binding))}</b></div></div><button className="text-button" onClick={() => setForm({ ...form, template: form.template + ` {{${binding.alias}}}` })}>插入引用<Plus size={13}/></button></div>; })}
      {!successful.length && <div className="empty-text"><p>当前项目没有成功完成的结果。</p><span>先在实验复现运行实验或在数据分析执行分析，再绑定真实指标。</span></div>}
    </section><div className="support-column"><section className="surface"><div className="section-heading"><h2>文稿预览</h2><span className="caption">当前编辑内容 · 数值来自绑定结果</span></div><pre className="manuscript-preview">{preview}</pre><p className="caption">只更新绑定变量，不自动改写解释性结论。预览不代表成果文件已经更新。</p></section><section className="surface"><div className="section-heading"><h2>比较图表</h2><ChartNoAxesCombined size={18} className="muted"/></div><p className="caption">选择来源与指标。不同指标分别作图，不补写缺失值。</p><div className="chart-sources">{successful.map(r => <label className="checkbox-row" key={r.id}><input type="checkbox" checked={form.chart_run_ids.includes(r.id)} onChange={() => chooseChartRun(r.id)}/><span>{r.name}<small>{r.config.recipe === 'analysis' ? '数据分析' : '实验运行'} · {time(r.created)}</small></span></label>)}</div>{availableMetrics.length > 0 && <div className="metric-checks">{availableMetrics.map(metric => <label className="checkbox-row" key={metric}><input type="checkbox" checked={form.chart_metrics.includes(metric)} onChange={e => setForm({ ...form, chart_metrics: e.target.checked ? [...form.chart_metrics, metric] : form.chart_metrics.filter(m => m !== metric) })}/><span>{metric}</span></label>)}</div>}</section>
      {record?.generated.id && <section className="surface"><div className="section-heading"><h2>已生成成果</h2><span className="caption">第{record.generated.version}版 · {time(record.generated.created!)}</span></div><div className="artifact-links">{record.generated.files?.map(f => <a key={f} href={`/api/projects/${project.id}/reports/${record.id}/artifacts/${f}?v=${record.generated.id}`} download><FileText size={14}/>{f}<Download size={13}/></a>)}</div>{record.generated.files?.includes('figure.png') && <img className="analysis-plot" src={`/api/projects/${project.id}/reports/${record.id}/artifacts/figure.png?v=${record.generated.id}`} alt="依据实际运行结果生成的比较图"/>}<button className="text-button" onClick={() => setSourcesOpen(!sourcesOpen)}><BookOpen size={14}/>{sourcesOpen ? '收起' : '查看'}来源说明</button>{sourcesOpen && <p className="caption">来源记录与文稿、图表一起保存在sources.json。Word使用本次生成版本的正文和数据；修改草稿或引用后需重新生成。支持标题、段落、列表、表格和可转换的LaTeX公式，外部图片不会自动嵌入。</p>}</section>}
    </div></div>
  </>;
}
