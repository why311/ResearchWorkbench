import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import ReadingQueue from './ReadingQueue';
import './reading-queue.css';

type Project = { id: string; name: string; question: string };
type Literature = { id: string; title: string; filename: string; pages: number; span_count: number };
type Annotation = { span_id: string; kind: 'highlight' | 'confused' | 'understood'; note: string; page?: number; quote?: string };
type Source = { title: string; items: { id: string; page: number; text: string }[]; total: number; has_more: boolean };
function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [projectId, setProjectId] = useState('');
  const [documents, setDocuments] = useState<Literature[]>([]);
  const [documentId, setDocumentId] = useState('');
  const [page, setPage] = useState(1);
  const [offset, setOffset] = useState(0);
  const [anchor, setAnchor] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [reading, setReading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [notes, setNotes] = useState<Record<string, Annotation>>({});
  const [queueRevision, setQueueRevision] = useState(0);
  const [notesRevision, setNotesRevision] = useState(0);
  const [notesLoading, setNotesLoading] = useState(false);
  const [noteBusy, setNoteBusy] = useState('');
  const [noteStatus, setNoteStatus] = useState('');
  const selected = documents.find(d => d.id === documentId);
  const read = async (path: string, options: RequestInit = {}) => {
    const response = await fetch('/api' + path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请重试');
    return data;
  };
  useEffect(() => { if (!projectId && projects.length) setProjectId(projects[0].id); }, [projects, projectId]);
  useEffect(() => {
    let live = true; setDocuments([]); setDocumentId(''); setSource(null);
    if (projectId) read('/projects/' + projectId).then(data => { if (live) setDocuments(data.documents); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [projectId, revision]);
  useEffect(() => {
    let live = true; setSource(null); setReading(!!documentId);
    if (projectId && documentId) read(`/projects/${projectId}/documents/${documentId}?page=${page}&offset=${offset}`).then(data => { if (live) setSource(data); }).catch(e => { if (live) setError(e.message); }).finally(() => { if (live) setReading(false); });
    return () => { live = false; };
  }, [projectId, documentId, page, offset]);
  useEffect(() => {
    let live = true; setNotes({}); setNoteStatus(''); setNotesLoading(!!documentId);
    if (projectId && documentId) read(`/projects/${projectId}/documents/${documentId}/annotations`).then(data => { if (live) { setNotes(Object.fromEntries(data.map((a: Annotation) => [a.span_id, a]))); setNotesLoading(false); } }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [projectId, documentId, notesRevision]);
  const editNote = (id: string, patch: Partial<Annotation>) => { setNoteStatus(''); setNotes(old => ({ ...old, [id]: { ...(old[id] || { span_id: id, kind: 'highlight', note: '' }), ...patch } })); };
  const saveNote = async (id: string) => {
    setNoteBusy(id); setError(''); setNoteStatus('');
    try { await read(`/projects/${projectId}/documents/${documentId}/annotations`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notes[id] || { span_id: id }) }); setNoteStatus('已保存 ' + id + ' 的批注'); setQueueRevision(n => n + 1); }
    catch (e) { setError((e as Error).message); } finally { setNoteBusy(''); }
  };
  useEffect(() => { if (source && anchor) document.getElementById('source-' + anchor)?.scrollIntoView({ block: 'center' }); }, [source, anchor]);
  const upload = async (file?: File) => {
    if (!file || !projectId) return;
    setUploading(true); setError('');
    try { const body = new FormData(); body.append('file', file); await read(`/projects/${projectId}/documents`, { method: 'POST', body }); setRevision(n => n + 1); }
    catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  };
  const load = async () => {
    setLoading(true); setError('');
    try { const response = await fetch('/api/projects'); if (!response.ok) throw new Error('项目读取失败'); setProjects(await response.json()); }
    catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);
  const create = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const response = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, question }) });
      if (!response.ok) throw new Error('项目创建失败，请检查名称和服务');
      const project = await response.json(); setProjects(old => [project, ...old]); setProjectId(project.id); setName(''); setQuestion('');
    } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  };
  return <main><header><span>研舟</span></header><h1>研究项目与文献</h1>{error && <div role="alert">{error}<button onClick={() => { load(); setRevision(n => n + 1); }}>重试</button></div>}<div className="workspace"><form onSubmit={create}><h2>开始一个项目</h2><label>项目名称<input aria-label="项目名称" required maxLength={100} value={name} onChange={e => setName(e.target.value)}/></label><label>研究问题<textarea aria-label="研究问题" rows={4} maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)}/></label><button className="primary" disabled={saving || !!noteBusy || !name.trim()}>{saving ? '保存中…' : '创建项目'}</button></form><section aria-label="项目列表">{loading ? <p role="status">正在读取项目…</p> : projects.length ? projects.map(p => <article key={p.id}><h2>{p.name}</h2><p>{p.question || '尚未填写研究问题'}</p><button disabled={uploading || !!noteBusy} onClick={() => setProjectId(p.id)} aria-pressed={projectId === p.id}>{projectId === p.id ? '当前项目' : '查看项目文献'}</button></article>) : <p className="muted">还没有项目，可以从左侧创建。</p>}</section></div>
    {projectId && <ReadingQueue key={projectId} refreshKey={queueRevision} onUpdated={() => setNotesRevision(n => n + 1)} projectId={projectId} documents={documents} noteLimit={4000} source={(did, sid, page, offset) => { setDocumentId(did); setPage(page); setOffset(offset); setAnchor(sid); }}/>}
    {projectId && <section className="literature"><h2>项目文献</h2><label>当前研究项目<select aria-label="当前研究项目" value={projectId} disabled={uploading || !!noteBusy} onChange={e => setProjectId(e.target.value)}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label>导入全文<input aria-label="导入全文" type="file" accept=".pdf,.md,.txt" disabled={uploading || !!noteBusy} onChange={e => { upload(e.target.files?.[0]); e.target.value = ''; }}/></label><p className="muted">PDF、UTF-8文本或Markdown；每篇最大20MB、300页、100万字符。本阶段不含OCR，扫描页需要先识别文字。</p>{uploading && <p role="status">正在导入并提取原文…</p>}<div className="document-list">{documents.map(d => <article key={d.id}><h3>{d.title}</h3><p>{d.filename} · {d.pages}页 · {d.span_count}段</p><button disabled={!!noteBusy} onClick={() => { setDocumentId(d.id); setPage(1); setOffset(0); }}>查看原文</button><a href={`/api/projects/${projectId}/documents/${d.id}/original`}>下载原文件</a></article>)}{!documents.length && <p className="muted">本项目还没有全文，导入后可按页阅读。</p>}</div>
      {selected && <article className="source"><h2>{selected.title}</h2><label>原文页码<input aria-label="原文页码" type="number" min={1} max={selected.pages} value={page} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= selected.pages) { setPage(n); setOffset(0); } }}/></label><p>第{page}/{selected.pages}页 · 本页{source?.total || 0}段</p><div className="page-actions"><a href={`/api/projects/${projectId}/documents/${documentId}/notes.md`}>导出阅读笔记</a><button disabled={reading || page === 1 && !offset} onClick={() => offset ? setOffset(n => Math.max(0, n - 100)) : setPage(n => n - 1)}>上一页段</button><button disabled={reading || !source || page === selected.pages && !source.has_more} onClick={() => { if (source?.has_more) setOffset(n => n + 100); else { setPage(n => n + 1); setOffset(0); } }}>下一页段</button></div>{reading && <p role="status">正在读取原文…</p>}{noteStatus && <p role="status">{noteStatus}</p>}{source?.items.map(s => <div className={'source-span' + (s.id === anchor ? ' focused-source' : '')} id={'source-' + s.id} key={s.id}><small>第{s.page}页 · {s.id}</small><p>{s.text}</p><div className="annotation"><label>阅读状态<select aria-label={`阅读状态 ${s.id}`} value={notes[s.id]?.kind || 'highlight'} disabled={notesLoading || !!noteBusy} onChange={e => editNote(s.id, { kind: e.target.value as Annotation['kind'] })}><option value="highlight">重点</option><option value="confused">待弄清</option><option value="understood">已理解</option></select></label><label>个人批注<textarea aria-label={`个人批注 ${s.id}`} rows={3} maxLength={4000} value={notes[s.id]?.note || ''} disabled={notesLoading || !!noteBusy} onChange={e => editNote(s.id, { note: e.target.value })}/></label><button disabled={notesLoading || !!noteBusy} onClick={() => saveNote(s.id)}>{noteBusy === s.id ? '保存中…' : '保存本段批注'}</button></div></div>)}{source && !source.items.length && <p>本页未提取到文字，请下载原文件核对。</p>}</article>}
    </section>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
