import { useEffect, useRef, useState } from 'react';
import { api, post, type ModuleProps, type SourcePage, type Span } from './api';
import './completion.css';

type Segment = Span & { translation: { text: string; method: string; reviewed: boolean } | null };
type ParallelPage = Omit<SourcePage, 'items'> & { items: Segment[] };
type Job = { status: string; completed: number; total: number; error: string };
const jobLabels: Record<string, string> = { queued: '排队中', running: '翻译中', completed: '已完成', cancelled: '已停止', interrupted: '已中断', failed: '失败', idle: '未开始' };

export default function ParallelReading({ project, busy, action, source, modelConfigured, settings }: ModuleProps & { source: (did: string, sid?: string) => void; modelConfigured: boolean; settings: () => void }) {
  const [did, setDid] = useState(project.documents[0]?.id || '');
  const doc = project.documents.find(d => d.id === did) || project.documents[0];
  const [language, setLanguage] = useState('zh');
  const [page, setPage] = useState(1), [offset, setOffset] = useState(0);
  const [data, setData] = useState<ParallelPage | null>(null), [error, setError] = useState('');
  const [revision, setRevision] = useState(0), [editing, setEditing] = useState(''), [text, setText] = useState(''), [reviewed, setReviewed] = useState(false);
  const [job, setJob] = useState<Job | null>(null), [sync, setSync] = useState(true), [hover, setHover] = useState(false);
  const [selection, setSelection] = useState<{ sid: string; text: string } | null>(null), [gloss, setGloss] = useState(''), [glossBusy, setGlossBusy] = useState(false);
  const left = useRef<HTMLDivElement>(null), right = useRef<HTMLDivElement>(null), syncing = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null), lastWord = useRef(''), request = useRef(0);
  const base = `/projects/${project.id}/documents/${doc?.id}`;
  useEffect(() => { setPage(1); setOffset(0); setEditing(''); setSelection(null); setGloss(''); setGlossBusy(false); lastWord.current=''; if(timer.current)clearTimeout(timer.current); request.current++; }, [doc?.id, language]);
  useEffect(()=>{setSelection(null);setGloss('');setGlossBusy(false);lastWord.current='';if(timer.current)clearTimeout(timer.current);request.current++;},[page,offset]);
  useEffect(()=>{if(job && ['completed','cancelled','failed','interrupted'].includes(job.status) && !editing)setRevision(n=>n+1);},[job?.status,editing]);
  useEffect(() => { let live = true; setData(null); setError(''); if (doc) api(`${base}/translations?language=${language}&page=${page}&offset=${offset}`).then(v => { if (live) setData(v); }).catch(e => { if (live) setError(e.message); }); return () => { live = false; }; }, [base, language, page, offset, revision]);
  useEffect(() => {
    let live = true;
    const read = () => { if (doc) api(`${base}/translation-job?language=${language}`).then(v => { if (live) setJob(v); }).catch(e => { if (live) setError(e.message); }); };
    read(); const interval = setInterval(read, 3000);
    return () => { live = false; clearInterval(interval); request.current++; if (timer.current) clearTimeout(timer.current); };
  }, [base, language]);
  const align = (from: HTMLDivElement, to: HTMLDivElement | null) => {
    if (!sync || !to || syncing.current) return;
    const articles = Array.from(from.querySelectorAll<HTMLElement>('[data-sid]'));
    const item = [...articles].reverse().find(el => el.offsetTop <= from.scrollTop + 3) || articles[0];
    if (!item) return;
    const target = Array.from(to.querySelectorAll<HTMLElement>('[data-sid]')).find(el => el.dataset.sid === item.dataset.sid);
    if (!target) return;
    syncing.current = true;
    const fraction = (from.scrollTop - item.offsetTop) / Math.max(1, item.offsetHeight);
    to.scrollTop = target.offsetTop + fraction * target.offsetHeight;
    requestAnimationFrame(() => { syncing.current = false; });
  };
  const translate = async (picked: { sid: string; text: string }) => {
    const id = ++request.current; setSelection(picked); setGloss(''); setGlossBusy(true);
    try { const result = await post(base + '/translate-selection', { span_id: picked.sid, selection: picked.text, language }); if (request.current === id) setGloss(result.translation); }
    catch (e) { if (request.current === id) setGloss((e as Error).message); }
    finally { if (request.current === id) setGlossBusy(false); }
  };
  const pick = (sid: string) => {
    const chosen = window.getSelection()?.toString().trim();
    if (chosen && chosen.length <= 3000) { setSelection({ sid, text: chosen }); setGloss(''); }
  };
  const move = (event: React.PointerEvent, sid: string) => {
    if (!hover || !modelConfigured) return;
    if (timer.current) clearTimeout(timer.current);
    const caret = (document as Document & { caretRangeFromPoint?: (x: number, y: number) => Range | null }).caretRangeFromPoint?.(event.clientX, event.clientY);
    if (!caret || caret.startContainer.nodeType !== Node.TEXT_NODE) return;
    const value = caret.startContainer.textContent || '', position = caret.startOffset;
    const word = Array.from(value.matchAll(/[\p{L}\p{N}_-]+/gu)).find(m => m.index! <= position && m.index! + m[0].length >= position)?.[0];
    if (word && word.length <= 100 && word !== lastWord.current) timer.current = setTimeout(() => { lastWord.current = word; void translate({ sid, text: word }); }, 800);
  };
  const save = () => action('translation-save', async () => { await api(base + '/translations/' + editing, { method: 'PUT', body: JSON.stringify({ language, text, reviewed }) }); setEditing(''); setRevision(n => n + 1); });
  const running = job && ['queued', 'running'].includes(job.status), locked = !!busy || !!editing;
  if (!doc) return <p className="empty-text">先导入全文，再开始双语阅读。</p>;
  return <section className="completion-workspace"><div className="section-heading"><h2>双语阅读</h2><a className="button secondary" href={`/api${base}/translations-export?language=${language}`}>导出双语包</a></div>
    <div className="completion-toolbar"><label>文献<select value={doc.id} disabled={locked} onChange={e => setDid(e.target.value)}>{project.documents.map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label><label>译文<select value={language} disabled={locked} onChange={e => setLanguage(e.target.value)}><option value="zh">中文</option><option value="en">English</option></select></label><label>页码<input aria-label="双语阅读页码" type="number" min={1} max={doc.pages} value={page} disabled={locked} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= doc.pages) { setPage(n); setOffset(0); } }}/></label><button className="button secondary" disabled={locked || page <= 1 && !offset} onClick={() => { if (offset) setOffset(Math.max(0, offset-40)); else setPage(n => n-1); }}>上一页段</button><button className="button secondary" disabled={locked || !data || page >= doc.pages && !data.has_more} onClick={() => { if (data?.has_more) setOffset(n => n+40); else { setOffset(0); setPage(n => n+1); } }}>下一页段</button></div>
    <div className="completion-toolbar"><label className="checkbox-row"><input type="checkbox" checked={sync} onChange={e => setSync(e.target.checked)}/>同步滚动</label><label className="checkbox-row"><input type="checkbox" checked={hover} onChange={e => setHover(e.target.checked)} disabled={!modelConfigured}/>悬停查词</label><button className="button secondary" disabled={locked || !modelConfigured || !data} onClick={() => action('translate-page', async () => { await post(base + '/translate', { language, page, offset }); setRevision(n => n+1); })}>翻译本页段</button><button className="button secondary" disabled={locked || !modelConfigured || !!running} onClick={() => action('translate-all', async () => setJob(await post(base + '/translation-job', { language, start_page: 1, end_page: doc.pages })))}>翻译全文缺失段落</button>{running && <button className="button secondary" onClick={() => action('stop-translation', async () => setJob(await api(`${base}/translation-job?language=${language}`, { method: 'DELETE' })))}>停止翻译</button>}</div>
    <p className="caption">翻译与查词会发送所选文字到模型服务；全文按页分批处理，可停止后继续，已有译文保留。{!modelConfigured && <button className="text-button" onClick={settings}>配置模型</button>}</p>
    {job && <p role="status">翻译任务：{jobLabels[job.status] || job.status} · 已处理{job.completed}/{job.total}段 {job.error}<button className="text-button" onClick={() => setRevision(n => n+1)}>读取最新译文</button></p>}{error && <p role="alert" className="feedback error">{error}<button onClick={() => setRevision(n => n+1)}>重试</button></p>}
    {selection && <aside className="selection-gloss" aria-live="polite"><div className="section-heading"><b>{selection.text}</b><button className="text-button" disabled={!modelConfigured || glossBusy} onClick={() => translate(selection)}>翻译选中文字</button><button className="text-button" onClick={() => { request.current++; setSelection(null); setGlossBusy(false); }}>关闭</button></div><p>{glossBusy ? '正在翻译…' : gloss}</p></aside>}
    {!data && !error && <p role="status">正在读取原文与译文…</p>}
    <div className="split-reading"><section><h3>原文</h3><div className="reading-pane" ref={left} onScroll={e => align(e.currentTarget, right.current)}>{data?.items.map(s => <article data-sid={s.id} key={s.id}><button className="text-button" onClick={() => source(doc.id, s.id)}>第{s.page}页 · {s.id}</button><p onPointerUp={() => pick(s.id)} onPointerMove={e => move(e, s.id)} onPointerLeave={() => { if (timer.current) clearTimeout(timer.current); }}>{s.text}</p></article>)}</div></section><section><h3>{language === 'zh' ? '中文译文' : 'English translation'}</h3><div className="reading-pane" ref={right} onScroll={e => align(e.currentTarget, left.current)}>{data?.items.map(s => <article data-sid={s.id} key={s.id}><p className="caption">{s.id} · {s.translation ? (s.translation.method === 'model' ? '模型草稿' : '人工保存') + (s.translation.reviewed ? ' · 已核对' : ' · 待核对') : '未翻译'}</p>{editing === s.id ? <><textarea aria-label="编辑译文" rows={7} maxLength={8000} value={text} onChange={e => { setText(e.target.value); setReviewed(false); }}/><label className="checkbox-row"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已对照原文核对</label><div className="inline-actions"><button className="button primary" disabled={!!busy || !text.trim()} onClick={save}>保存</button><button className="button secondary" onClick={() => setEditing('')}>取消</button></div></> : <><p>{s.translation?.text || '可手动填写或生成译文。'}</p><button className="text-button" disabled={locked} onClick={() => { setEditing(s.id); setText(s.translation?.text || ''); setReviewed(!!s.translation?.reviewed); }}>编辑译文</button></>}</article>)}</div></section></div>
  </section>;
}
