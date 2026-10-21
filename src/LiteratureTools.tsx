import { useEffect, useState } from 'react';
import { BookOpen, Check, Download, GitBranch, Languages, LoaderCircle, Pencil, Search, Trash2 } from 'lucide-react';
import { api, post, type ModuleProps, type SourcePage, type Span } from './api';
import './literature.css';

type Props = ModuleProps & { source: (did: string, sid?: string) => void };
type Translation = { text: string; method: string; reviewed: boolean; updated: string };
type ParallelPage = Omit<SourcePage, 'items'> & { items: (Span & { translation: Translation | null })[]; warnings?: string[] };

export function BilingualReader({ project, busy, action, source, modelConfigured, settings }: Props & { modelConfigured: boolean; settings: () => void }) {
  const [did, setDid] = useState(project.documents[0]?.id || '');
  const doc = project.documents.find(d => d.id === did) || project.documents[0];
  const [language, setLanguage] = useState('zh');
  const [page, setPage] = useState(1);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ParallelPage | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState('');
  const [text, setText] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const base = `/projects/${project.id}/documents/${doc?.id}`;
  const address = `${base}/translations?language=${language}&page=${page}&offset=${offset}`;
  useEffect(() => { setPage(1); setOffset(0); }, [doc?.id]);
  useEffect(() => {
    let live = true; setData(null); setError('');
    if (doc) api(address).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [address, reload, doc?.ingestion?.completed]);
  const generate = () => action('translate', async () => setData(await post(base + '/translate', { language, page, offset })), '译文草稿已保存，请对照原文核对数字、符号和语义');
  const save = () => action('translation-save', async () => {
    await api(base + '/translations/' + editing, { method: 'PUT', body: JSON.stringify({ language, text, reviewed }) });
    setData(await api(address)); setEditing('');
  }, '译文与核对状态已保存');
  if (!doc) return <div className="empty"><Languages size={32}/><h3>先导入需要对照阅读的原文</h3><p>支持逐段填写译文；配置模型后可生成草稿。</p></div>;
  const locked = !!busy || !!editing;
  return <section className="parallel-reader">
    <div className="section-heading"><div><h2>双语对照阅读</h2><p className="caption">原文与译文逐段对应。模型草稿和作者核对分别标记，翻译不代替原文依据。</p></div><a className="button secondary" href={`/api${base}/translations-export?language=${language}`}><Download size={15}/>导出双语阅读包</a></div>
    <div className="literature-toolbar"><label>当前文献<select aria-label="双语阅读文献" disabled={locked} value={doc.id} onChange={e => setDid(e.target.value)}>{project.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label>译文语言<select aria-label="译文语言" disabled={locked} value={language} onChange={e => setLanguage(e.target.value)}><option value="zh">中文</option><option value="en">English</option></select></label><label>页码<input aria-label="双语阅读页码" disabled={locked} type="number" min={1} max={doc.pages} value={page} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= doc.pages) { setPage(n); setOffset(0); } }}/></label><span>/ {doc.pages}页</span></div>
    <div className="parallel-actions"><div className="inline-actions"><button className="button secondary" disabled={locked || !data || page <= 1 && !offset} onClick={() => { if (offset) setOffset(Math.max(0, offset - 40)); else setPage(p => p - 1); }}>上一页段</button><button className="button secondary" disabled={locked || !data || page >= doc.pages && !data.has_more} onClick={() => { if (data?.has_more) setOffset(n => n + 40); else { setOffset(0); setPage(p => p + 1); } }}>下一页段</button></div><button className="button primary" disabled={locked || !modelConfigured || !data?.items.some(s => !s.translation)} onClick={generate}>{busy === 'translate' ? <LoaderCircle size={15} className="spin"/> : <Languages size={15}/>}生成本页段缺失译文</button></div>
    <p className="caption">{modelConfigured ? '点击生成会把本页段尚无译文的原文发送到已配置的模型服务；每批最多40段、20000字符，已有译文保留。' : <>未配置模型，仍可手动填写和导出译文。<button className="text-button" onClick={settings}>配置模型服务</button></>}{editing && ' 当前正在编辑，请保存或取消后切换文献和页码。'}</p>
    {error && <div className="feedback error" role="alert">{error}<button onClick={() => setReload(v => v + 1)}>重试</button></div>}
    {data?.warnings?.map(w => <p className="reading-warning" key={w}>{w}</p>)}
    {!data && !error && <p role="status"><LoaderCircle size={16} className="spin"/>正在读取原文与译文…</p>}
    {data && !data.items.length && <p className="empty-text">本页尚未识别到文字，请查看文档结构中的原页和解析状态。</p>}
    {data?.items.map(span => <article className="parallel-passage" key={span.id}><div className="parallel-source"><div><h3>原文 · 第{span.page}页 · {span.id}</h3><button className="text-button" onClick={() => source(doc.id, span.id)}><BookOpen size={14}/>回看原文</button></div><p>{span.text}</p>{span.confidence !== undefined && <small>OCR文字，请核对原页</small>}</div><div className="parallel-translation"><div><h3>{language === 'zh' ? '中文译文' : 'English translation'}</h3><span className="caption">{span.translation ? `${span.translation.method === 'model' ? '模型草稿' : '人工保存'} · ${span.translation.reviewed ? '作者已核对' : '待核对'}` : '尚未填写'}</span></div>{editing === span.id ? <><label>译文<textarea aria-label="编辑译文" rows={8} maxLength={8000} value={text} onChange={e => { setText(e.target.value); setReviewed(false); }}/></label><label className="literature-check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>我已对照原文核对本段译文</label><div className="inline-actions"><button className="button primary" disabled={!!busy || !text.trim()} onClick={save}><Check size={14}/>保存译文</button><button className="button secondary" disabled={!!busy} onClick={() => setEditing('')}>取消</button></div></> : <><p className={span.translation ? '' : 'empty-text'}>{span.translation?.text || '填写本段译文，或配置模型后生成草稿。'}</p><button className="text-button" disabled={locked} onClick={() => { setEditing(span.id); setText(span.translation?.text || ''); setReviewed(!!span.translation?.reviewed); }}><Pencil size={13}/>{span.translation ? '修改译文' : '填写译文'}</button></>}</div></article>)}
    {data && <p className="caption">本页共{data.total}段，当前显示第{data.items.length ? offset + 1 : 0}—{offset + data.items.length}段；导出包含本篇已保存译文及对应原文。</p>}
  </section>;
}

type Reference = { id: string; document_id: string; span_id: string; identifier: string; label: string; quote: string; status: string; target_document_id: string | null; url: string };
type Network = { documents: { id: string; title: string }[]; references: Reference[]; scope: string };

function ReferenceEditor({ row, documents, locked, save }: { row: Reference; documents: Network['documents']; locked: boolean; save: (body: any) => Promise<void> }) {
  const [label, setLabel] = useState(row.label);
  const [target, setTarget] = useState(row.target_document_id || '');
  const [status, setStatus] = useState(row.status);
  return <details className="reference-editor"><summary>编辑名称、关联全文和核对状态</summary><label>被引文献名称<input maxLength={300} value={label} onChange={e => setLabel(e.target.value)}/></label><label>关联项目内全文<select value={target} onChange={e => setTarget(e.target.value)}><option value="">尚未关联全文</option>{documents.filter(d => d.id !== row.document_id).map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label className="literature-check"><input type="checkbox" checked={status === 'confirmed'} onChange={e => setStatus(e.target.checked ? 'confirmed' : 'candidate')}/>已核对原文，这是一条参考文献引用</label><button className="button secondary" disabled={locked || !label.trim()} onClick={() => save({ label, status, target_document_id: target || null })}>保存引用记录</button></details>;
}

export function CitationNetwork({ project, busy, action, source }: Props) {
  const [did, setDid] = useState(project.documents[0]?.id || '');
  const doc = project.documents.find(d => d.id === did) || project.documents[0];
  const [start, setStart] = useState(1);
  const [end, setEnd] = useState(1);
  const [network, setNetwork] = useState<Network | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState('');
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  useEffect(() => { setStart(Math.max(1, (doc?.pages || 1) - 3)); setEnd(doc?.pages || 1); }, [doc?.id, doc?.pages]);
  const base = `/projects/${project.id}`;
  useEffect(() => {
    let live = true; setError('');
    api(base + '/reference-network').then(v => { if (live) setNetwork(v); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, reload, project.documents.length]);
  const refresh = async () => setNetwork(await api(base + '/reference-network'));
  const extract = () => action('reference-extract', async () => {
    const result = await post(base + `/documents/${doc.id}/references-extract`, { start_page: start, end_page: end });
    setNotice(`识别到${result.found}个标识，新增${result.created}条候选。${result.message}`); await refresh();
  });
  if (!doc) return <div className="empty"><GitBranch size={32}/><h3>先导入包含参考文献的全文</h3><p>从指定页识别DOI、arXiv标识，核对后连接到项目中的其他文献。</p></div>;
  const allRows = network?.references || [];
  const outgoing = allRows.filter(r => r.document_id === doc.id && (!confirmedOnly || r.status === 'confirmed'));
  const incoming = allRows.filter(r => r.target_document_id === doc.id && (!confirmedOnly || r.status === 'confirmed'));
  const nodes = outgoing.slice(0, 20);
  const graphHeight = Math.max(155, nodes.length * 82 + 30);
  return <section className="citation-workspace"><div className="section-heading"><div><h2>文献引用关系</h2><p className="caption">先识别候选，再核对引用。连线从当前文献指向被引文献。</p></div><a className="button secondary" href={`/api${base}/reference-network/export`}><Download size={15}/>导出引用记录</a></div>
    <div className="literature-toolbar"><label>来源全文<select aria-label="引用来源全文" value={doc.id} disabled={!!busy} onChange={e => { setDid(e.target.value); setNotice(''); }}>{project.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label>参考文献起始页<input aria-label="引用起始页" type="number" min={1} max={doc.pages} value={start} onChange={e => setStart(Number(e.target.value))}/></label><label>结束页<input aria-label="引用结束页" type="number" min={1} max={doc.pages} value={end} onChange={e => setEnd(Number(e.target.value))}/></label><button className="button primary" disabled={!!busy || !Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start || end > doc.pages || end - start >= 30} onClick={extract}><Search size={15}/>提取引用候选</button></div>
    <p className="caption">每次最多30页、200000字符；只提取可定位的DOI/arXiv标识，不自动推断无标识的题名。请指定实际参考文献页；正文提及、OCR误识别仍可能混入候选。</p>
    {notice && <p className="reference-notice" role="status">{notice}</p>}{error && <div role="alert" className="feedback error">{error}<button onClick={() => setReload(n => n + 1)}>重新读取</button></div>}
    <div className="reference-summary"><p>{allRows.filter(r => r.document_id === doc.id && r.status === 'confirmed').length}条已确认引用 · {allRows.filter(r => r.document_id === doc.id && r.status === 'candidate').length}条待核对候选</p><label className="literature-check"><input type="checkbox" checked={confirmedOnly} onChange={e => setConfirmedOnly(e.target.checked)}/>只看已确认关系</label></div>
    {!network && !error && <p role="status">正在读取项目引用记录…</p>}
    {network && !outgoing.length && <div className="empty"><GitBranch size={30}/><h3>{confirmedOnly ? '这篇文献还没有已确认引用' : '从参考文献页开始建立关系'}</h3><p>提取候选后回看原文，填写名称并核对；关联已导入全文后可查看项目内的被引关系。</p></div>}
    {nodes.length > 0 && <><div className="citation-diagram"><svg viewBox={`0 0 900 ${graphHeight}`} role="img" aria-label={`${doc.title}指向${nodes.length}条被引候选或已确认引用的关系图`}><defs><marker id="reference-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>{nodes.map((r, i) => <path key={r.id} className={r.status === 'confirmed' ? 'confirmed' : 'candidate'} d={`M 330 ${graphHeight / 2} C 430 ${graphHeight / 2}, 430 ${i * 82 + 50}, 540 ${i * 82 + 50}`} markerEnd="url(#reference-arrow)"/>)}<g><rect x="20" y={graphHeight / 2 - 31} width="310" height="62" rx="6"/><text x="38" y={graphHeight / 2 + 5}>{doc.title.slice(0, 24)}{doc.title.length > 24 ? '…' : ''}</text></g>{nodes.map((r, i) => <g key={r.id}><rect x="540" y={i * 82 + 19} width="340" height="62" rx="6"/><text x="554" y={i * 82 + 45}>{r.label.slice(0, 26)}{r.label.length > 26 ? '…' : ''}</text><text className="diagram-state" x="554" y={i * 82 + 64}>{r.status === 'confirmed' ? '作者已核对' : '待核对候选'}{r.target_document_id ? ' · 已关联全文' : ''}</text></g>)}</svg></div><p className="caption">实线：作者已确认引用；虚线：待核对候选。关系图显示前20条，下面保留全部记录；完整名称和来源可在列表核对。</p></>}
    <div className="reference-list">{outgoing.map(row => <article key={row.id}><div className="reference-row-heading"><h3>{row.label}</h3><span className={'badge ' + (row.status === 'confirmed' ? 'succeeded' : 'neutral')}>{row.status === 'confirmed' ? '作者已核对' : '待核对候选'}</span></div><p className="caption">{row.identifier}</p><blockquote>{row.quote}</blockquote><div className="inline-actions"><button className="text-button" onClick={() => source(row.document_id, row.span_id)}><BookOpen size={14}/>核对来源原文</button>{row.target_document_id && <button className="text-button" onClick={() => source(row.target_document_id!)}>查看已关联全文</button>}<a className="text-button" href={row.url} target="_blank" rel="noreferrer">打开文献标识</a><button className="text-button" disabled={!!busy} onClick={() => action('reference-remove', async () => { await api(base + '/references/' + row.id, { method: 'DELETE' }); await refresh(); }, '候选已移除；需要时可从相同页重新提取')}><Trash2 size={13}/>移除记录</button></div><ReferenceEditor key={row.id + row.status + (row.target_document_id || '') + row.label} row={row} documents={network!.documents} locked={!!busy} save={body => action('reference-save', async () => { await api(base + '/references/' + row.id, { method: 'PUT', body: JSON.stringify(body) }); await refresh(); }, '引用记录已保存')}/></article>)}</div>
    <section className="incoming-references"><h3>项目中引用这篇全文的文献</h3>{incoming.length ? incoming.map(r => <p key={r.id}><button className="text-button" onClick={() => source(r.document_id, r.span_id)}>{network?.documents.find(d => d.id === r.document_id)?.title} · {r.status === 'confirmed' ? '作者已核对' : '候选'}</button></p>) : <p className="empty-text">尚无关联到这篇全文的引用记录。需要在来源文献中明确关联全文。</p>}</section>
    <p className="caption">{network?.scope}</p>
  </section>;
}
