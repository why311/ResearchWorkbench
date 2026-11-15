import { useEffect, useState } from 'react';
import { BookOpen, Download, FilePlus2, RefreshCw } from 'lucide-react';
import { api, post, type ModuleProps, type Span } from './api';
import './research-discovery.css';

type Node = { id: string; title: string; incoming: number; outgoing: number; pagerank: number; isolated: boolean; role: 'core' | 'derivative' | 'connected' | 'isolated' };
type ReferenceCandidate = { id: string; document_id: string; target_document_id: string; span_id: string; label: string; quote: string };
type FutureReview = { items: { id: string; sources: Future['items']; resolution: { title: string; url: string; year: string; reason: string; quote: string } | null }[]; reviewed: number; scope: string };
type Graph = { review_candidates?: ReferenceCandidate[]; review_total?: number; candidate_edges?:{source:string;target:string}[]; nodes: Node[]; edges: { source: string; target: string }[]; components: string[][]; summary: string; scope: string; excluded_references: number };
type Future = { items: (Span & { document_id: string; title: string; reason: string })[]; truncated: boolean; scope: string };

export default function GraphInsights({ project, busy, action, source }: ModuleProps & { source: (did: string, sid?: string) => void }) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [future, setFuture] = useState<Future | null>(null);
  const [review, setReview] = useState<FutureReview | null>(null);
  const [publicQuery, setPublicQuery] = useState('');
  const [showResolved, setShowResolved] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [idea, setIdea] = useState(project.question);
  const [created, setCreated] = useState('');
  const [matched,setMatched]=useState<any>(null);
  const base = `/projects/${project.id}`;
  useEffect(() => {
    let live = true; setError('');
    Promise.all([api(base + '/graph-insights'), api(base + '/future-work')]).then(([g, f]) => { if (live) { setGraph(g); setFuture(f); } }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, revision, project.documents.length]);
  const nodes = graph?.nodes.slice(0, 30) || [];
  const positions = new Map(nodes.map((n, i) => [n.id, { x: 250 + 190 * Math.cos(2 * Math.PI * i / nodes.length - Math.PI / 2), y: 250 + 190 * Math.sin(2 * Math.PI * i / nodes.length - Math.PI / 2) }]));
  const create = () => action('outline-create', async () => {
    const report = await post(base + '/literature-outline', { idea, document_ids: selected });
    setCreated(report.title);
  }, '研究框架已保存到成果同步');
  return <section className="discovery-workspace">
    <div className="section-heading"><h2>全项目图谱分析</h2><div className="inline-actions"><button className="button secondary" disabled={!!busy||project.documents.length<2} onClick={()=>action('match-references',async()=>{setMatched(await post(base+'/reference-network/match'));setRevision(n=>n+1);})}>匹配项目内引用</button><button className="button secondary" disabled={!!busy} onClick={() => setRevision(n => n + 1)}><RefreshCw size={15}/>刷新分析</button><a className="button secondary" href={`/api${base}/graph-insights/mermaid`}><Download size={15}/>Mermaid脚本</a></div></div>
    {matched&&<p role="status">新增{matched.created}条候选，{matched.ambiguous}处存在歧义。{matched.scope}</p>}
    {error && <p className="feedback error" role="alert">{error}</p>}
    {!graph && !error && <p role="status">正在计算项目引用关系…</p>}
    {graph?.candidate_edges?.length? <p className="caption">虚线表示待核对引用，不参与节点排名。</p>:null}
    {graph && <><p className="discovery-summary">{graph.summary} 另有{graph.excluded_references}条候选或未关联引用未参与计算。</p>
      <div className="graph-analysis-grid"><div className="graph-figure"><svg viewBox="0 0 500 500" role="img" aria-label="项目有向引用图，节点编号对应右侧文献表"><defs><marker id="analysis-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L10 5 L0 10Z"/></marker></defs>{graph.candidate_edges?.filter(e=>positions.has(e.source)&&positions.has(e.target)).map(e=>{const a=positions.get(e.source)!,b=positions.get(e.target)!;return <line className="candidate-edge" key={'candidate-'+e.source+e.target} x1={a.x} y1={a.y} x2={b.x} y2={b.y}/>;})}{graph.edges.filter(e => positions.has(e.source) && positions.has(e.target)).map(e => { const a = positions.get(e.source)!, b = positions.get(e.target)!, distance = Math.hypot(b.x - a.x, b.y - a.y); return <line key={e.source + e.target} x1={a.x} y1={a.y} x2={b.x - (b.x - a.x) * 20 / distance} y2={b.y - (b.y - a.y) * 20 / distance} markerEnd="url(#analysis-arrow)"/>; })}{nodes.map((node, i) => { const p = positions.get(node.id)!; return <g key={node.id}><title>{node.title} · 项目内被引{node.incoming}篇</title><circle cx={p.x} cy={p.y} r={14 + 8 * node.pagerank / Math.max(...nodes.map(n => n.pagerank))} className={node.isolated ? 'isolated' : ''}/><text x={p.x} y={p.y + 5} textAnchor="middle">{i + 1}</text></g>; })}</svg><p className="caption">箭头指向被引全文。图中显示前30篇；下表保留全部节点和连接。</p></div>
      <div className="table-scroll graph-rankings"><table><thead><tr><th>文献</th><th>项目内被引</th><th>PageRank</th></tr></thead><tbody>{graph.nodes.map((node, index) => <tr key={node.id}><td><button className="text-button" onClick={() => source(node.id)}>{index + 1}. {node.title}</button><details><summary>{node.outgoing}条向外引用{node.role === 'core' ? ' · 基石候选' : node.role === 'derivative' ? ' · 衍生候选' : node.isolated ? ' · 无已确认连接' : ''}</summary>{graph.edges.filter(e => e.source === node.id).map(e => <button className="text-button" key={e.target} onClick={() => source(e.target)}>{graph.nodes.find(n => n.id === e.target)?.title}</button>)}</details></td><td>{node.incoming}</td><td>{node.pagerank.toFixed(4)}</td></tr>)}</tbody></table></div></div>
      <p className="caption">{graph.scope}</p></>}
    {!!graph?.review_candidates?.length && <details className="discovery-section"><summary>核对引用候选（{graph.review_candidates.length}/{graph.review_total}）</summary>{graph.review_candidates.map(item => <article className="future-source" key={item.id}>
      <h3>{graph.nodes.find(node => node.id === item.document_id)?.title} → {item.label}</h3>
      <blockquote>{item.quote}</blockquote><div className="inline-actions">
        <button className="text-button" onClick={() => source(item.document_id, item.span_id)}>回看引用原文</button>
        <button className="button secondary" disabled={!!busy} onClick={() => action('confirm-citation-edge', async () => {
          await api(base + '/references/' + item.id, { method: 'PUT', body: JSON.stringify({ label: item.label, status: 'confirmed', target_document_id: item.target_document_id }) });
          setRevision(n => n + 1);
        })}>确认引用</button></div></article>)}</details>}
    <section className="discovery-section"><h2>后续研究原文</h2><p className="caption">{future?.scope}</p>{future?.truncated && <p role="status">当前展示前60段，请按文献继续核对。</p>}{future && !future.items.length && <p className="empty-text">尚未找到明确的展望词句；这不表示论文没有后续研究内容。</p>}{!!future?.items.length && <form className="completion-toolbar" onSubmit={e => {
      e.preventDefault(); action('review-future-work', async () => { setReview(await post(base + '/future-work/review', { public_query: publicQuery })); setShowResolved(false); });
    }}><label>发送给 arXiv 的公开检索词<input value={publicQuery} onChange={e => setPublicQuery(e.target.value)} maxLength={300} required /></label>
      <button className="button secondary" disabled={!!busy || publicQuery.trim().length < 2}>用后续论文核对</button></form>}
    {review && <><p role="status">已核对 {review.reviewed} 组。{review.scope}</p>
      <label className="checkbox-row"><input type="checkbox" checked={showResolved} onChange={e => setShowResolved(e.target.checked)}/>显示已找到回应的 {review.items.filter(i => i.resolution).length} 组</label>
      {review.items.filter(i => !i.resolution || showResolved).map(item => <article className="future-source" key={item.id}>
        <p>{item.sources[0].text}</p>{item.sources.map(s => <button key={s.document_id + s.id} className="text-button" onClick={() => source(s.document_id, s.id)}>{s.title} · 第{s.page}页</button>)}
        {item.resolution && <><p>{item.resolution.reason}</p><blockquote>{item.resolution.quote}</blockquote><a href={item.resolution.url} target="_blank" rel="noreferrer">{item.resolution.title} · {item.resolution.year}</a></>}
      </article>)}</>}
    {!review && future?.items.map(s => <article className="future-source" key={s.document_id + s.id}><div className="section-heading"><h3>{s.title} · 第{s.page}页</h3><button className="button secondary" onClick={() => source(s.document_id, s.id)}><BookOpen size={14}/>回看原文</button></div><p>{s.text}</p></article>)}</section>
    <section className="discovery-section"><h2>研究写作框架</h2><form onSubmit={e => { e.preventDefault(); create(); }}><label>研究想法<textarea aria-label="研究想法" required maxLength={1000} value={idea} onChange={e => setIdea(e.target.value)} rows={3}/></label><fieldset className="outline-documents"><legend>引用全文（最多15篇）</legend>{project.documents.map(d => <label key={d.id}><input type="checkbox" checked={selected.includes(d.id)} disabled={!!busy || selected.length >= 15 && !selected.includes(d.id)} onChange={e => setSelected(ids => e.target.checked ? [...ids, d.id] : ids.filter(id => id !== d.id))}/>{d.title}</label>)}</fieldset><button className="button primary" disabled={!!busy || !idea.trim() || !selected.length}><FilePlus2 size={15}/>{busy === 'outline-create' ? '正在保存…' : '保存框架到成果同步'}</button></form><p className="caption">按选定原文建立写作提纲与来源引用；事实、书目信息和结论由作者补齐。</p>{created && <p className="feedback success" role="status">已保存“{created}”，可在成果同步中编辑和导出。</p>}</section>
  </section>;
}
