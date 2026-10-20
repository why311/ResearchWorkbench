import { useEffect, useState } from 'react';
import { LoaderCircle, X } from 'lucide-react';
import { api, type Doc, type SourcePage } from './api';

export default function SourcePanel({ selected, close, projectId }: { selected: { document: Doc; span?: string }; close: () => void; projectId: string }) {
  const [page, setPage] = useState(Number(selected.span?.match(/^p(\d+)-/)?.[1] || 1));
  const [offset, setOffset] = useState(0);
  const [anchor, setAnchor] = useState(selected.span || '');
  const [data, setData] = useState<SourcePage | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const dialog = document.querySelector<HTMLDialogElement>('#source-dialog');
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  useEffect(() => { setPage(Number(selected.span?.match(/^p(\d+)-/)?.[1] || 1)); setOffset(0); setAnchor(selected.span || ''); }, [selected]);
  useEffect(() => {
    let live = true;
    setError(''); setData(null);
    const target = anchor ? '&anchor=' + encodeURIComponent(anchor) : '';
    api(`/projects/${projectId}/documents/${selected.document.id}/spans?page=${page}&offset=${offset}${target}`).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [projectId, selected, page, offset, anchor, reload]);
  useEffect(() => { if (data) document.getElementById('source-' + selected.span)?.scrollIntoView({ block: 'center' }); }, [data, selected.span]);
  const currentOffset = data?.offset ?? offset;
  return <dialog id="source-dialog" className="source-panel" aria-label="原文阅读面板" onCancel={close} onClick={e => { if (e.target === e.currentTarget && e.clientX < e.currentTarget.getBoundingClientRect().left) close(); }}><div className="source-header"><div><span className="small-label">原文阅读</span><h2>{selected.document.title}</h2><p>{selected.document.pages}页 · 提取文字保留页码 · 按页加载</p></div><button className="icon-button" aria-label="关闭原文" onClick={close} autoFocus><X size={20}/></button></div><div className="source-pagination"><label>页码<input aria-label="原文阅读页码" type="number" min={1} max={selected.document.pages} value={page} onChange={e => { const p = Number(e.target.value); if (Number.isInteger(p) && p >= 1 && p <= selected.document.pages) { setPage(p); setOffset(0); setAnchor(''); } }}/></label><span>/ {selected.document.pages}</span><button className="button secondary" disabled={page <= 1 && !currentOffset} onClick={() => { setAnchor(''); if (currentOffset) setOffset(Math.max(0, currentOffset - 200)); else { setOffset(0); setPage(p => p - 1); } }}>上一页段</button><button className="button secondary" disabled={!data || page >= selected.document.pages && !data.has_more} onClick={() => { setAnchor(''); if (data?.has_more) setOffset(currentOffset + 200); else { setOffset(0); setPage(p => p + 1); } }}>下一页段</button></div><div className="source-body">{error ? <div role="alert"><p>{error}</p><button className="text-button" onClick={() => setReload(v => v + 1)}>重新读取</button></div> : !data ? <p role="status"><LoaderCircle size={18} className="spin"/>正在读取原文…</p> : <>{!data.items.length && <p className="empty-text">本页尚未解析或未提取到文字，请对照原文件与解析状态。</p>}{data.items.map(s => <article id={'source-' + s.id} key={s.id} className={s.id === selected.span ? 'highlighted' : ''}><span>第{s.page}页 · {s.id}{s.confidence !== undefined ? ' · OCR文字需核对' : ''}</span><p>{s.text}</p></article>)}</>}</div></dialog>;
}
