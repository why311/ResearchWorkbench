import { useEffect, useState } from 'react';
import { LoaderCircle, X } from 'lucide-react';
import { api, type Doc, type SourcePage } from './api';
import { CitationText, type CitationRef } from './CitationLinks';
import './completion.css';

export default function SourcePanel({ selected, close, projectId }: { selected: { document: Doc; span?: string }; close: () => void; projectId: string }) {
  const [page, setPage] = useState(Number(selected.span?.match(/^p(\d+)-/)?.[1] || 1));
  const [offset, setOffset] = useState(0);
  const [anchor, setAnchor] = useState(selected.span || '');
  const [data, setData] = useState<SourcePage | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [references, setReferences] = useState<CitationRef[]>([]);
  const [mapError, setMapError] = useState('');
  const [original, setOriginal] = useState(false);
  useEffect(() => { let live = true; setReferences([]); setMapError(''); api(`/projects/${projectId}/documents/${selected.document.id}/citation-map`).then(data => { if (live) setReferences(data.references); }).catch(e => { if (live) setMapError(e.message); }); return () => { live = false; }; }, [projectId, selected.document.id]);
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
  useEffect(() => { if (data) document.getElementById('source-' + anchor)?.scrollIntoView({ block: 'center' }); }, [data, anchor]);
  const jump = (sid: string) => { setPage(Number(sid.match(/^p(\d+)-/)?.[1] || 1)); setAnchor(sid); setOffset(0); };
  const currentOffset = data?.offset ?? offset;
  return <dialog id="source-dialog" className="source-panel" aria-label="原文阅读面板" onCancel={close} onClick={e => { if (e.target === e.currentTarget && e.clientX < e.currentTarget.getBoundingClientRect().left) close(); }}><div className="source-header"><div><h2>{selected.document.title}</h2></div><button className="icon-button" aria-label="关闭原文" onClick={close} autoFocus><X size={20}/></button></div><div className="source-pagination"><label>页码<input aria-label="原文阅读页码" type="number" min={1} max={selected.document.pages} value={page} onChange={e => { const p = Number(e.target.value); if (Number.isInteger(p) && p >= 1 && p <= selected.document.pages) { setPage(p); setOffset(0); setAnchor(''); } }}/></label><span>/ {selected.document.pages}</span>{selected.document.has_original && selected.document.filename.toLowerCase().endsWith('.pdf') && <button className="button secondary" onClick={()=>setOriginal(v=>!v)}>{original?'收起PDF原件':'对照PDF原件'}</button>}<button className="button secondary" disabled={page <= 1 && !currentOffset} onClick={() => { setAnchor(''); if (currentOffset) setOffset(Math.max(0, currentOffset - 200)); else { setOffset(0); setPage(p => p - 1); } }}>上一页段</button><button className="button secondary" disabled={!data || page >= selected.document.pages && !data.has_more} onClick={() => { setAnchor(''); if (data?.has_more) setOffset(currentOffset + 200); else { setOffset(0); setPage(p => p + 1); } }}>下一页段</button></div><div className="source-body">{original && <iframe title="PDF原件阅读器" src={`/api/projects/${projectId}/documents/${selected.document.id}/original#page=${page}`} style={{width:'100%',height:'65vh',border:0}}/>}{mapError && <p role="alert">引用定位暂不可用：{mapError}</p>}{error ? <div role="alert"><p>{error}</p><button className="text-button" onClick={() => setReload(v => v + 1)}>重新读取</button></div> : !data ? <p role="status"><LoaderCircle size={18} className="spin"/>正在读取原文…</p> : <>{!data.items.length && <p className="empty-text">本页尚未解析或未提取到文字，请对照原文件与解析状态。</p>}{data.items.map(s => <article id={'source-' + s.id} key={s.id} className={s.id === anchor ? 'highlighted' : ''}><span>第{s.page}页 · {s.id}{s.confidence !== undefined ? ' · OCR文字需核对' : ''}</span><p><CitationText text={s.text} references={references} jump={jump}/></p>{references.find(r => r.span_id === s.id)?.backlinks.map((b,i) => <button className="button secondary" key={b.span_id+i} onClick={() => jump(b.span_id)}>返回正文第{b.page}页</button>)}</article>)}</>}</div></dialog>;
}
