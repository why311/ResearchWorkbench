import { useEffect, useState } from 'react';
import { BookOpen, Download, GitBranch, Search, Trash2 } from 'lucide-react';
import { api, post, type ModuleProps } from './api';
import './literature.css';

type Props = ModuleProps & { source: (did: string, sid?: string) => void };
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
