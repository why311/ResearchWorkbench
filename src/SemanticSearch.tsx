import { useEffect, useState } from 'react';
import { BookOpen, Download, LoaderCircle, Search, Square } from 'lucide-react';
import { api, post, type Evidence, type ModuleProps } from './api';

type Index = { document_id: string; status: string; completed: number; total: number; error: string; model_revision: string };
type State = { ready: boolean; preparing: boolean; error: string; model: string; revision: string; indexes: Index[] };
type Hit = Evidence & { similarity?: number; matched_text?: string; routes: string[] };
const names: Record<string, string> = { queued: '等待索引', running: '建立中', ready: '可检索', failed: '失败', cancelled: '已停止', interrupted: '已中断' };

export default function SemanticSearch({ project, busy, action, source }: ModuleProps & { source: (did: string, sid?: string) => void }) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState(project.question);
  const [selected, setSelected] = useState(project.documents.slice(0, 8).map(d => d.id));
  const [hybrid, setHybrid] = useState(true);
  const [result, setResult] = useState<{ evidence: Hit[]; note: string } | null>(null);
  const [reload, setReload] = useState(0);
  const base = `/projects/${project.id}`;
  useEffect(() => {
    let live = true;
    const load = () => api(base + '/semantic-indexes').then(v => { if (live) { setState(v); setError(''); } }).catch(e => { if (live) setError(e.message); });
    load(); const timer = setInterval(load, 2000);
    return () => { live = false; clearInterval(timer); };
  }, [base, reload]);
  const search = () => action('semantic-search', async () => setResult(await post(base + '/semantic-search', { question: query, document_ids: selected, hybrid })));
  const ready = !!state?.ready && selected.length > 0 && selected.every(id => state.indexes.some(i => i.document_id === id && i.status === 'ready' && i.model_revision === state.revision));
  return <section className="semantic-search surface"><div className="section-heading"><div><h2>跨语言语义检索</h2><p className="caption">用中文问题查找英文原文，也可结合关键词排名。结果仍指向原文，不把相似度当作事实置信度。</p></div><button className="button secondary" disabled={!!busy || state?.ready || state?.preparing} onClick={() => action('semantic-prepare', async () => { await post('/semantic/prepare'); setReload(n => n + 1); })}>{state?.preparing ? <LoaderCircle size={15} className="spin"/> : <Download size={15}/>} {state?.ready ? '本地模型已就绪' : state?.preparing ? '正在准备本地模型…' : '准备本地语义模型'}</button></div><p className="caption">首次准备需要联网下载多语言模型；原文索引和问题计算在本机完成，不发送研究原文。每篇最多20000个窗口，每次检索最多8篇、合计32000个窗口。</p>
    {(error || state?.error) && <p className="feedback error" role="alert">{error || state?.error}</p>}
    {!project.documents.length && <p className="empty-text">先导入全文，再建立可复用的本地索引。</p>}
    <fieldset className="semantic-documents"><legend>选择全文并建立索引</legend>{project.documents.map(doc => { const index = state?.indexes.find(i => i.document_id === doc.id); const active = index && ['running', 'queued'].includes(index.status); return <div key={doc.id}><label><input type="checkbox" checked={selected.includes(doc.id)} disabled={!!busy || !selected.includes(doc.id) && selected.length >= 8} onChange={e => { setSelected(ids => e.target.checked ? [...ids, doc.id] : ids.filter(id => id !== doc.id)); setResult(null); }}/><span>{doc.title}<small>{index ? `${index.status === 'ready' && state?.ready && index.model_revision !== state.revision ? '模型版本变化，请重建' : names[index.status]} · ${index.completed}/${index.total}个窗口` : '尚未建立语义索引'}</small></span></label><button className="text-button" disabled={!!busy || !state?.ready} onClick={() => action('semantic-build', async () => { await post(base + `/documents/${doc.id}/semantic-index${active ? '/cancel' : ''}`); setReload(n => n + 1); })}>{active ? <><Square size={13}/>停止索引</> : index?.status === 'ready' ? '重新建立索引' : '建立索引'}</button>{index?.error && <p role="status">{index.error}</p>}</div>; })}</fieldset>
    <label>检索问题<textarea aria-label="语义检索问题" disabled={!!busy} rows={3} maxLength={1000} value={query} onChange={e => { setQuery(e.target.value); setResult(null); }}/></label><label className="literature-check"><input type="checkbox" disabled={!!busy} checked={hybrid} onChange={e => { setHybrid(e.target.checked); setResult(null); }}/>同时结合关键词检索</label><button className="button primary" disabled={!!busy || !ready || query.trim().length < 2} onClick={search}>{busy === 'semantic-search' ? <LoaderCircle size={15} className="spin"/> : <Search size={15}/>}检索原文</button>{!ready && <p className="caption">准备模型，并完成所选全文的索引后即可检索。</p>}
    {result && <div className="semantic-results"><h3>检索到的原文候选</h3><p className="caption">{result.note}</p>{result.evidence.length ? result.evidence.map(hit => <article key={hit.citation}><div><h4>{hit.title} · 第{hit.page}页</h4><small>{hit.routes.map(r => r === 'semantic' ? '语义' : '关键词').join(' + ')}{hit.similarity !== undefined ? ` · 余弦相似度${hit.similarity.toFixed(3)}` : ''}</small></div><p>{hit.matched_text || hit.text}</p><button className="text-button" onClick={() => source(hit.document_id, hit.id)}><BookOpen size={14}/>回看完整原文片段 · {hit.id}</button></article>) : <p className="empty-text">未检索到候选，可补充相关全文或改写问题。</p>}</div>}
  </section>;
}
