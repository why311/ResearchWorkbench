import { useEffect, useState } from 'react';
import { Download, RefreshCw, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react';
import { api, post, type ModuleProps } from './api';
import './research-discovery.css';

type Watch = { id: string; query: string; enabled: number; interval_hours: number; last_checked: string | null; next_check: string; error: string };
type Paper = { watch_id: string; key: string; arxiv_id: string; title: string; abstract: string; authors: string[]; updated: string; published: string; repositories: string[]; url: string; reasons: string[]; similarity: number; rating: number; document_id: string | null };
type Feed = { watches: Watch[]; items: Paper[]; scope: string };

export default function PaperWatch({ project, busy, action, source }: ModuleProps & { source: (did: string) => void }) {
  const [data, setData] = useState<Feed | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [filter, setFilter] = useState('');
  const [codeFirst, setCodeFirst] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [notice, setNotice] = useState('');
  const base = `/projects/${project.id}/paper-watches`;
  const reload = async () => setData(await api(base));
  useEffect(() => { let live = true; setError(''); api(base).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); }); return () => { live = false; }; }, [base, revision, project.documents.length]);
  const mutate = (key: string, task: () => Promise<any>) => action(key, async () => { try { await task(); } finally { await reload(); } });
  const items = (data?.items || []).filter(p => (!filter || p.watch_id === filter) && (showHidden || p.rating !== -1)).sort((a, b) => (codeFirst ? Number(!!b.repositories.length) - Number(!!a.repositories.length) : 0) || b.similarity - a.similarity || b.updated.localeCompare(a.updated));
  const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未刷新';
  return <section className="discovery-workspace"><div className="section-heading"><h2>文献追踪</h2><button className="button secondary" disabled={!!busy} onClick={() => setRevision(n => n + 1)}><RefreshCw size={15}/>读取已保存结果</button></div>
    <form className="watch-create" onSubmit={e => { e.preventDefault(); mutate('watch-create', async () => { await post(base, { query, enabled: false, interval_hours: 24 }); setQuery(''); }); }}><label>关键词或arXiv检索式<input aria-label="关键词或arXiv检索式" required minLength={2} maxLength={300} placeholder="例如 ti:transformer 或 arXiv:1706.03762" value={query} onChange={e => setQuery(e.target.value)}/></label><button className="button primary" disabled={!!busy || query.trim().length < 2}>保存追踪</button></form>
    <p className="caption">刷新会将检索词发送给arXiv。题录不作为全文依据；点击下载后进入本机PDF解析。</p>
    {error && <p className="feedback error" role="alert">{error}</p>}{!data && !error && <p role="status">正在读取追踪…</p>}
    <div className="watch-list">{data?.watches.map(w => <article key={w.id}><div className="section-heading"><h3>{w.query}</h3><div className="inline-actions"><button className="button secondary" disabled={!!busy} onClick={() => mutate('watch-refresh', () => post(base + `/${w.id}/refresh`))}><RefreshCw size={14}/>{busy === 'watch-refresh' ? '刷新中…' : '立即刷新'}</button><button className="icon-button" aria-label={`删除追踪${w.query}`} disabled={!!busy} onClick={() => mutate('watch-delete', async () => { await api(base + '/' + w.id, { method: 'DELETE' }); if (filter === w.id) setFilter(''); })}><Trash2 size={16}/></button></div></div><div className="watch-controls"><label className="literature-check"><input type="checkbox" checked={!!w.enabled} disabled={!!busy} onChange={e => mutate('watch-update', () => api(base + '/' + w.id, { method: 'PUT', body: JSON.stringify({ ...w, enabled: e.target.checked }) }))}/>自动刷新</label><label>刷新间隔<select aria-label={`刷新间隔${w.query}`} value={w.interval_hours} disabled={!!busy} onChange={e => mutate('watch-update', () => api(base + '/' + w.id, { method: 'PUT', body: JSON.stringify({ ...w, interval_hours: Number(e.target.value), enabled: !!w.enabled }) }))}>{[6, 12, 24, 48, 72, 168].map(n => <option value={n} key={n}>{n}小时</option>)}</select></label><p>上次：{date(w.last_checked)}{!!w.enabled && <> · 下次：{date(w.next_check)}</>}</p></div>{w.error && <p role="alert" className="reading-warning">{w.error}</p>}</article>)}</div>
    {data && !data.watches.length && <p className="empty-text">保存一个研究主题，再刷新查看最新题录。</p>}
    {!!data?.watches.length && <><div className="literature-toolbar"><label>追踪主题<select value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部主题</option>{data.watches.map(w => <option value={w.id} key={w.id}>{w.query}</option>)}</select></label><label className="literature-check"><input type="checkbox" checked={codeFirst} onChange={e => setCodeFirst(e.target.checked)}/>GitHub链接优先</label><label className="literature-check"><input type="checkbox" checked={showHidden} onChange={e => setShowHidden(e.target.checked)}/>显示不感兴趣</label></div><p className="caption">{data.scope}</p><p className="discovery-summary">当前{items.length}条题录；点赞会参与本地词项排序，不将相似度视为质量评分。</p></>}
    {notice && <p className="feedback success" role="status">{notice}</p>}
    <div className="paper-feed">{items.map(p => <article key={p.watch_id + p.key}><h3><a href={p.url} target="_blank" rel="noreferrer">{p.title}</a></h3><p className="caption">{p.authors.join('，')} · {p.arxiv_id} · 更新于{date(p.updated)}</p><details><summary>摘要</summary><p className="paper-abstract">{p.abstract}</p></details><ul className="paper-reasons">{p.reasons.map(r => <li key={r}>{r}</li>)}</ul><div className="inline-actions">{p.repositories.map(url => <a key={url} href={url} target="_blank" rel="noreferrer" className="button secondary">GitHub仓库</a>)}{p.document_id ? <button className="button secondary" onClick={() => source(p.document_id!)}>查看已导入全文</button> : <button className="button secondary" disabled={!!busy} onClick={() => mutate('watch-import', async () => { const r = await post(base + `/${p.watch_id}/import`, { arxiv_id: p.key }); setNotice(r.existing ? '全文已在项目中，可到文档结构查看。' : 'PDF已接收，解析进度见文档结构。'); })}><Download size={15}/>{busy === 'watch-import' ? '正在下载…' : '下载并解析全文'}</button>}<button className="button secondary" aria-pressed={p.rating === 1} disabled={!!busy} onClick={() => mutate('watch-rate', () => api(base + `/${p.watch_id}/feedback`, { method: 'PUT', body: JSON.stringify({ arxiv_id: p.key, rating: p.rating === 1 ? 0 : 1 }) }))}><ThumbsUp size={14}/>感兴趣</button><button className="button secondary" aria-pressed={p.rating === -1} disabled={!!busy} onClick={() => mutate('watch-rate', () => api(base + `/${p.watch_id}/feedback`, { method: 'PUT', body: JSON.stringify({ arxiv_id: p.key, rating: p.rating === -1 ? 0 : -1 }) }))}><ThumbsDown size={14}/>不感兴趣</button></div></article>)}</div>
  </section>;
}
