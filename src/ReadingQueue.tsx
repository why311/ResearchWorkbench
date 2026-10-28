import { useEffect, useState } from 'react';
import { api } from './api';

type Question = { id: string; document_id: string; title: string; span_id: string; quote: string; page: number | null; offset: number; kind: string; note: string };
type Result = { items: Question[]; total: number; has_more: boolean };
const labels: Record<string, string> = { confused: '待解决', understood: '已理解', highlight: '重点', note: '笔记', verbose: '需精简' };

export default function ReadingQueue({ projectId, documents, source, noteLimit, refreshKey = 0, onUpdated }: {
  projectId: string; documents: { id: string; title: string }[]; noteLimit: number; refreshKey?: number; onUpdated?: () => void;
  source: (did: string, sid: string, page: number, offset: number) => void;
}) {
  const [kind, setKind] = useState('confused');
  const [documentId, setDocumentId] = useState('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState('');
  const [draft, setDraft] = useState('');
  useEffect(() => {
    let live = true; setData(null); setError(''); setEditing('');
    const params = new URLSearchParams({ kind, document_id: documentId, q: query, offset: String(offset) });
    api(`/projects/${projectId}/reading-questions?${params}`).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [projectId, kind, documentId, query, offset, revision, refreshKey]);
  const save = async (item: Question, understood = false) => {
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/projects/${projectId}/reading-questions/${item.document_id}/${item.id}`, { method: 'PUT', body: JSON.stringify({ kind: understood ? 'understood' : item.kind, note: understood ? item.note : draft }) });
      onUpdated?.();
      setNotice(understood ? '已标为已理解' : '笔记已更新'); setEditing(''); setOffset(0); setRevision(n => n + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="surface reading-queue" aria-label="阅读待办">
    <div className="section-heading"><h2>阅读待办</h2>{data && <span className="caption">{data.total}条</span>}</div>
    <div className="queue-filters"><label>状态<select aria-label="待办状态" value={kind} disabled={busy} onChange={e => { setKind(e.target.value); setOffset(0); setNotice(''); }}><option value="confused">待解决</option><option value="understood">已理解</option><option value="all">全部批注</option></select></label>
      <label>文献<select aria-label="待办文献" value={documentId} disabled={busy} onChange={e => { setDocumentId(e.target.value); setOffset(0); setNotice(''); }}><option value="">全部文献</option>{documents.map(d => <option value={d.id} key={d.id}>{d.title}</option>)}</select></label>
      <form onSubmit={e => { e.preventDefault(); setQuery(search.trim()); setOffset(0); setRevision(n => n + 1); }}><label>搜索笔记或篇名<input aria-label="搜索阅读待办" value={search} maxLength={200} onChange={e => setSearch(e.target.value)}/></label><button className="button secondary" disabled={busy}>搜索</button></form>
    </div>
    {error && <div role="alert"><p>{error}</p><button className="text-button" disabled={busy} onClick={() => setRevision(n => n + 1)}>重新读取待办</button></div>}
    {notice && <p role="status">{notice}</p>}
    {!data && !error && <p role="status">正在读取批注…</p>}
    {data && !data.items.length && <p className="empty-text">{query || documentId ? '没有匹配的批注。' : kind === 'confused' ? '暂无待解决批注。' : '暂无这类批注。'}</p>}
    {data?.items.map(item => { const key = item.document_id + '/' + item.id; return <article className="queue-item" key={key}>
      <div className="queue-item-heading"><h3>{item.title}</h3><span>{labels[item.kind] || item.kind} · {item.page ? `第${item.page}页` : '来源待核对'}</span></div>
      <blockquote>{item.quote}</blockquote>
      {editing === key ? <><label>笔记<textarea aria-label="修改待办笔记" value={draft} maxLength={noteLimit} rows={4} disabled={busy} onChange={e => setDraft(e.target.value)}/></label><div className="inline-actions"><button className="button primary" disabled={busy} onClick={() => save(item)}>保存修改</button><button className="button secondary" disabled={busy} onClick={() => setEditing('')}>取消修改</button></div></> : <>
        <p className="queue-note">{item.note || '尚未填写笔记'}</p><div className="inline-actions"><button className="button secondary" disabled={busy || !!editing} onClick={() => { setEditing(key); setDraft(item.note); }}>修改笔记</button>{item.kind === 'confused' && <button className="button primary" disabled={busy || !!editing} onClick={() => save(item, true)}>标为已理解</button>}</div>
      </>}
      <button className="text-button" onClick={() => source(item.document_id, item.span_id, item.page || 1, item.offset)}>回看原文</button>
    </article>; })}
    {data && (offset > 0 || data.has_more) && <div className="inline-actions"><button className="button secondary" disabled={!offset || busy} onClick={() => setOffset(n => Math.max(0, n - 50))}>上一组待办</button><button className="button secondary" disabled={!data.has_more || busy} onClick={() => setOffset(n => n + 50)}>下一组待办</button></div>}
  </section>;
}
