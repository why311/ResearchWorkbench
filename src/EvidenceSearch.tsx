import { useState } from 'react';
import { api } from './api';

type Hit = { id: string; document_id: string; title: string; page: number; offset: number; text: string };
type Result = { query: string; items: Hit[]; searched_documents: number; searched_passages: number; scope: string };

export default function EvidenceSearch({ projectId, documents, source }: { projectId: string; documents: { id: string; title: string }[]; source: (did: string, sid: string, page: number, offset: number) => void }) {
  const [query, setQuery] = useState('');
  const [did, setDid] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [searchedDid, setSearchedDid] = useState('');
  const search = async () => {
    setLoading(true); setError(''); setResult(null);
    try { setResult(await api(`/projects/${projectId}/evidence-search?q=${encodeURIComponent(query)}&document_id=${encodeURIComponent(did)}`)); setSearchedDid(did); }
    catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  return <section className="evidence-search"><h2>检索文献原文</h2><form onSubmit={e => { e.preventDefault(); search(); }}><label>研究问题或关键词<input aria-label="研究问题或关键词" required minLength={2} maxLength={200} value={query} onChange={e => setQuery(e.target.value)}/></label><label>检索范围<select aria-label="检索范围" value={did} disabled={loading} onChange={e => { setDid(e.target.value); setResult(null); }}><option value="">全部项目文献</option>{documents.map(d => <option value={d.id} key={d.id}>{d.title}</option>)}</select></label><button className="primary" disabled={loading || query.trim().length < 2 || !documents.length}>{loading ? '正在检索…' : '检索原文'}</button></form>{error && <p role="alert">{error}</p>}{result && <><p className="muted">已检索{result.searched_documents}篇、{result.searched_passages}段。{result.scope}</p><a className="evidence-export" href={`/api/projects/${projectId}/evidence-search/export?q=${encodeURIComponent(result.query)}&document_id=${encodeURIComponent(searchedDid)}`}>导出检索来源JSON</a>{result.items.length ? result.items.map(hit => <article key={hit.document_id + hit.id}><h3>{hit.title} · 第{hit.page}页</h3><p>{hit.text}</p><button onClick={() => source(hit.document_id, hit.id, hit.page, hit.offset)}>定位原文 · {hit.id}</button></article>) : <p className="muted">没有找到匹配候选，请换用原文术语或缩小到单篇；不会补写答案。</p>}</>}{!documents.length && <p className="muted">先导入全文，再检索可回看的证据片段。</p>}</section>;
}
