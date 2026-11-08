import { useState, useEffect, useRef } from 'react';
import { Upload, Download, Plus, FileText, Play, Layers, Check, Trash2, RefreshCw, BookOpen, ArrowRight, LoaderCircle, ChartNoAxesCombined, Workflow, Square, Pencil } from 'lucide-react';
import { api, post, type ExperimentProps, type Dataset, type Run } from './api';

type Plan = { columns: string[]; missing: string; deduplicate: boolean; scales: Record<string, number>; filters: { column: string; minimum: number | null; maximum: number | null }[]; methods: string[]; group_by: string; x_column?: string };
const statusNames: Record<string, string> = { queued: '等待运行', running: '运行中', succeeded: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断', timeout: '已超时' };
const syncNames: Record<string, string> = { new: '尚未生成', synced: '已同步', stale: '需要更新', invalid: '引用待修复' };
const format = (value: number | null | undefined, precision = 4) => value === undefined || value === null ? '—' : Number.isInteger(value) ? String(value) : value.toFixed(precision);
const time = (value: string) => new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const artifactUrl = (pid: string, rid: string, name: string) => `/api/projects/${pid}/runs/${rid}/artifacts/${name}`;

export function AnalysisModule({ project, busy, action }: ExperimentProps) {
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
    <div className="page-heading"><div><h1>数据分析</h1></div><label className="button secondary file-button"><Upload size={16}/>{busy === 'dataset' ? '导入中…' : '导入数据'}<input type="file" accept=".csv,.tsv,.xlsx" disabled={!!busy} onChange={e => { load(e.target.files?.[0]); e.target.value = ''; }}/></label></div>
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
        <h3 className="subheading">计算内容</h3><div className="method-checks"><span className="badge neutral">描述统计始终提供</span><label className="checkbox-row"><input type="checkbox" checked={plan.methods.includes('groups')} onChange={() => toggleMethod('groups')}/><span>分组描述比较</span></label>{plan.methods.includes('groups') && <label>分组字段<select aria-label="分组字段" value={plan.group_by} onChange={e => setPlan({ ...plan, group_by: e.target.value })}><option value="">请选择分类字段</option>{selected.columns.filter(c => !plan.columns.includes(c)).map(c => <option key={c}>{c}</option>)}</select></label>}<label className="checkbox-row"><input type="checkbox" checked={plan.methods.includes('correlation')} onChange={() => toggleMethod('correlation')}/><span>Pearson相关分析<small>至少两个数值字段；不据此判断因果或显著性</small></span></label>{plan.methods.includes('line') && <label>折线图横轴<select value={plan.x_column || ''} onChange={e=>setPlan({...plan,x_column:e.target.value})}><option value="">清洗后原始行号</option>{plan.columns.map(c=><option key={c}>{c}</option>)}</select></label>}{[['line','折线图'],['radar','雷达图'],['radar3d','三维雷达图']].map(([key,label]) => <label className="checkbox-row" key={key}><input type="checkbox" checked={plan.methods.includes(key)} onChange={() => toggleMethod(key)}/><span>{label}</span></label>)}</div>
        <div className="analysis-start"><span className="caption">非数值内容记为缺失并记录数量</span><button className="button primary" disabled={!!busy || !name.trim() || !plan.columns.length || (plan.methods.includes('groups') && !plan.group_by) || (plan.methods.includes('correlation') && plan.columns.length < 2)} onClick={run}>{busy === 'analysis' ? <LoaderCircle className="spin" size={16}/> : <Play size={16}/>}执行分析</button></div>
      </> : <div className="empty compact"><ChartNoAxesCombined size={32}/><h3>从真实数据开始</h3><p>第一行作为字段名。Excel读取首张工作表，公式需先转为数值。</p><label className="button primary file-button"><Upload size={16}/>选择数据文件<input type="file" accept=".csv,.tsv,.xlsx" disabled={!!busy} onChange={e => { load(e.target.files?.[0]); e.target.value = ''; }}/></label><button className="text-button" disabled={!!busy} onClick={() => action('data-demo', async () => { const d = await post(`/projects/${project.id}/datasets/demo`); setDatasetId(d.id); }, '人工示例数据已载入')}>载入流程示例<ArrowRight size={14}/></button></div>}
      {csvRuns.length > 0 && <details className="details import-results"><summary>从实验记录导入结果表</summary><select aria-label="选择结果来源运行" value={selectedImport?.id || ''} onChange={e => setImportRun(e.target.value)}>{csvRuns.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select><div className="artifact-links">{selectedImport?.artifacts.filter(f => /\.(csv|tsv)$/i.test(f)).map(f => <button className="text-button" key={f} disabled={!!busy} onClick={() => action('data-import', async () => { const d = await post(`/projects/${project.id}/datasets/from-run`, { run_id: selectedImport.id, filename: f }); setDatasetId(d.id); }, '实验结果表已导入')}>{f}<Plus size={13}/></button>)}</div></details>}
    </section><div className="support-column analysis-output"><section className="surface"><div className="section-heading"><h2>数据预览</h2><span className="caption">原始值 · 前15行</span></div>{selected ? <div className="table-scroll preview-table"><table><thead><tr>{selected.columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{selected.profile.preview.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j}>{v || <span className="muted">缺失</span>}</td>)}</tr>)}</tbody></table></div> : <p className="empty-text">上传数据后，可核对字段、缺失情况与原始内容。</p>}</section>
      <section className="surface"><div className="section-heading"><h2>分析结果</h2>{current && <span className={'badge ' + current.status}>{statusNames[current.status]}</span>}</div>{runs.length > 0 && <label className="first-label">查看已保存的分析<select aria-label="查看已保存的分析" value={current?.id || ''} onChange={e => { setResultId(e.target.value); setDetail(null); }}>{runs.map(r => <option key={r.id} value={r.id}>{r.name} · {statusNames[r.status]}</option>)}</select></label>}
        {current ? <><div className="result-meta"><span>来源：{current.config.dataset_name}</span><span>{time(current.created)}</span></div><div className="inline-actions result-actions"><button className="text-button" onClick={() => { pendingPlan.current = current.config.dataset_id === selected?.id ? null : { id: current.config.dataset_id, plan: current.config.plan }; setDatasetId(current.config.dataset_id); setPlan(current.config.plan); setName(current.name.slice(0, 85) + ' · 复跑'); }}>载入此处理计划<RefreshCw size={14}/></button>{current.status === 'succeeded' && <a className="button secondary" href={`/api/projects/${project.id}/analysis/${current.id}/export`}><Download size={14}/>导出复跑包</a>}{['running', 'queued'].includes(current.status) && <button className="text-button" onClick={() => action('stop', () => post(`/projects/${project.id}/runs/${current.id}/cancel`))}><Square size={13}/>停止</button>}</div>
          {resultMatches && result ? <><div className="audit-line">输入{result.audit.input_rows}行 → 输出{result.audit.output_rows}行<span>去重{result.audit.duplicates_removed} / 筛除{result.audit.filtered_rows} / 缺失删行{result.audit.missing_rows_removed} / 填补{result.audit.imputed_cells} / 无效数值{result.audit.invalid_cells}</span></div><div className="tabs mini-tabs">{[['summary', '统计'], ['groups', '分组'], ['correlations', '相关'], ['files', '图表与文件']].map(([key, label]) => <button key={key} className={resultTab === key ? 'selected' : ''} onClick={() => setResultTab(key)}>{label}</button>)}</div>
            {resultTab === 'summary' && <StatsTable rows={result.summary}/>}{resultTab === 'groups' && (result.groups.length ? <StatsTable rows={result.groups} group/> : <p className="empty-text">此运行未选择分组比较。</p>)}{resultTab === 'correlations' && (result.correlations.length ? <div className="table-scroll"><table><thead><tr><th>字段X</th><th>字段Y</th><th>有效对数</th><th>Pearson r</th></tr></thead><tbody>{result.correlations.map((r: any, i: number) => <tr key={i}><td>{r.x}</td><td>{r.y}</td><td>{r.n}</td><td>{format(r.pearson_r)}</td></tr>)}</tbody></table></div> : <p className="empty-text">此运行未选择相关分析。</p>)}{resultTab === 'files' && <><div className="artifact-links">{current.artifacts.map(f => <a key={f} href={artifactUrl(project.id, current.id, f)} download><FileText size={14}/>{f}<Download size={13}/></a>)}</div>{current.artifacts.filter(f => f.endsWith('.png')).map(f => <figure className="analysis-figure" key={f}><img className="analysis-plot" src={artifactUrl(project.id, current.id, f)} alt={`实际分析图表 ${f}`}/><figcaption>{result.captions?.[f]}</figcaption></figure>)}</>}
            <details className="details"><summary>计算口径与实际日志</summary><ul className="analysis-notes">{result.notes.map((note: string) => <li key={note}>{note}</li>)}</ul><pre className="log">{detail?.run.log}</pre></details>
          </> : <div className="analysis-pending">{['running', 'queued'].includes(current.status) ? <p><LoaderCircle className="spin" size={17}/>正在实际执行分析…</p> : <p>未生成成功结果，请查看日志。</p>}<pre className="log">{resultMatches ? detail?.run.log || '等待进程输出…' : '读取运行记录…'}</pre></div>}
        </> : <div className="empty compact"><Play size={27}/><h3>结果由实际执行产生</h3><p>确认左侧处理计划后开始分析，统计、图表和复跑代码会一起保存。</p></div>}
      </section></div></div>
  </>;
}

function StatsTable({ rows, group = false }: { rows: any[]; group?: boolean }) {
  return <div className="table-scroll"><table className="stats-table"><thead><tr>{group && <th>分组</th>}<th>字段</th><th>有效n</th><th>缺失</th><th>均值</th><th>中位数</th><th>样本标准差</th><th>最小值</th><th>最大值</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{group && <td>{r.group}</td>}<td>{r.column}</td>{['count', 'missing', 'mean', 'median', 'std', 'min', 'max'].map(k => <td key={k}>{format(r[k])}</td>)}</tr>)}</tbody></table></div>;
}
