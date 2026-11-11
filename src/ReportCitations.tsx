import { useEffect, useState } from 'react';
import { BookOpen, Plus, Trash2 } from 'lucide-react';
import { api, type ModuleProps, type Citation, type SourcePage } from './api';

export default function ReportCitations({ project, source, citations, onChange, onInsert, template, disabled }: {
  project: ModuleProps['project']; source: (did: string, sid?: string) => void; citations: Citation[]; onChange: (values: Citation[]) => void;
  onInsert: (alias: string) => void; template: string; disabled: boolean;
}) {
  const [documentId, setDocumentId] = useState(project.documents[0]?.id || '');
  const [page, setPage] = useState(1);
  const [offset, setOffset] = useState(0);
  const [spanId, setSpanId] = useState('');
  const [data, setData] = useState<SourcePage | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const document = project.documents.find(d => d.id === documentId);
  const used = [...new Set([...template.matchAll(/\[\[cite:([A-Za-z][A-Za-z0-9_]{0,39})\]\]/g)].map(m => m[1]))];
  useEffect(() => {
    let live = true; setData(null); setError(''); setSpanId('');
    if (documentId) api(`/projects/${project.id}/documents/${documentId}/spans?page=${page}&offset=${offset}`).then(value => {
      if (live) { setData(value); setSpanId(value.items[0]?.id || ''); }
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [project.id, documentId, page, offset, revision]);
  const selected = data?.items.find(s => s.id === spanId);
  const add = () => {
    if (!selected || !document) return;
    let n = citations.length + 1;
    while (citations.some(c => c.alias === `source_${n}`)) n++;
    onChange([...citations, { alias: `source_${n}`, document_id: document.id, span_id: selected.id }]);
  };
  return <div className="report-citations">
    <div className="section-heading bindings-heading"><h3>引用文献原文</h3><BookOpen size={16}/></div>
    <p className="caption">导出保留篇名、页码和原文，论据是否支持结论需作者核对。</p>
    {!project.documents.length ? <p className="empty-text">先在“文献与开题”导入全文，即可把原文带进成果。</p> : <>
      <label>来源文献<select aria-label="引用来源文献" value={documentId} disabled={disabled} onChange={e => { setDocumentId(e.target.value); setPage(1); setOffset(0); }}><option value="" disabled>选择来源文献</option>{project.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
      {document && <>{document.pages > 1 && <label>来源页码<input aria-label="引用来源页码" type="number" min={1} max={document.pages} value={page} disabled={disabled} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= document.pages) { setPage(n); setOffset(0); } }}/></label>}
        {error ? <div role="alert"><p>{error}</p><button className="text-button" onClick={() => setRevision(n => n + 1)}>重新读取引用原文</button></div> : !data ? <p role="status">正在读取本页原文…</p> : <>
          <label>原文段落<select aria-label="引用原文段落" value={spanId} disabled={disabled || !data.items.length} onChange={e => setSpanId(e.target.value)}>{!data.items.length && <option value="">本页暂无已提取段落</option>}{data.items.map(s => <option key={s.id} value={s.id}>{s.id} · {s.text.slice(0, 65)}</option>)}</select></label>
          {(offset > 0 || data.has_more) && <div className="inline-actions" style={{ flexWrap: 'wrap' }}><button className="text-button" disabled={!offset || disabled} onClick={() => setOffset(n => Math.max(0, n - 200))}>上一组原文</button><button className="text-button" disabled={!data.has_more || disabled} onClick={() => setOffset(n => n + 200)}>下一组原文</button></div>}
          {selected && <><pre className="manuscript-preview">第{selected.page}页 · {selected.id}{selected.confidence !== undefined ? ' · OCR文字需核对' : ''}{'\n\n'}{selected.text}</pre><button className="text-button" disabled={disabled || citations.length >= 30 || citations.some(c => c.document_id === document.id && c.span_id === selected.id)} onClick={add}><Plus size={14}/>加入文献引用</button></>}
        </>}
      </>}
    </>}
    {citations.map((c, i) => { const doc = project.documents.find(d => d.id === c.document_id); return <div className="binding-row" key={c.alias}><p><b>{used.includes(c.alias) ? `正文[${used.indexOf(c.alias) + 1}]` : '尚未插入正文'}</b> · {doc?.title || '来源文献已移除'} · {c.span_id}</p><div className="inline-actions" style={{ flexWrap: 'wrap' }}><button className="text-button" disabled={disabled || !doc} onClick={() => onInsert(c.alias)}>插入正文</button><button className="text-button" disabled={!doc} onClick={() => doc && source(doc.id, c.span_id)}>回看引用原文</button><button className="icon-button" aria-label={`移除文献引用${i + 1}`} disabled={disabled} onClick={() => onChange(citations.filter(x => x.alias !== c.alias))}><Trash2 size={15}/></button></div></div>; })}
  </div>;
}
