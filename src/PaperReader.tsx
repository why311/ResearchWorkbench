import { useEffect, useState } from 'react';
import katex from 'katex';
import { ArrowRight, BookOpen, Check, Download, FileText, Lightbulb, LoaderCircle, MessageSquareText, Pencil, Plus, Quote, SearchCheck, Settings, Trash2, Undo2, X } from 'lucide-react';
import { api, post, type ModuleProps, type PaperReading, type ReadingEntry, type ReadingAnnotation } from './api';
import 'katex/dist/katex.min.css';
import './reader.css';

const sections = [
  { id: 'insight', title: '问题与洞见', question: '旧方法在什么场景失效，关键改变解决了什么？' },
  { id: 'mechanism', title: '机制与设定', question: '跟踪一次输入；指出关键设定及它防止的失效。' },
  { id: 'math', title: '公式与手算', question: '先写符号含义、形状与假设，再逐步验算一个小例子。' },
  { id: 'experiments', title: '实验与证据', question: '对照是否公平，差异是否大于波动，结论能支持到哪里？' },
  { id: 'bench', title: '复现诊断', question: '出现什么症状时，先做哪个低成本诊断；补丁代价是什么？' },
  { id: 'limits', title: '局限与下一步', question: '本次材料缺什么信息，接下来用什么实验核对？' }
];
const grades: Record<string, string> = { stated: '原文有据', inferred: '推断', speculative: '猜测', unreported: '本次材料未找到' };
const feedbackKinds: Record<string, string> = { highlight: '重点', note: '笔记', confused: '不懂', verbose: '太长', understood: '已懂' };
const freshEntry = (section: string): ReadingEntry => ({ id: crypto.randomUUID(), section, title: '', body: '', grade: 'inferred', span_ids: [], rationale: '', diagnostic: '', cost: '' });
type Props = ModuleProps & { initialDocument?: string; source: (did: string, sid?: string) => void; modelConfigured: boolean; settings: () => void };

export default function PaperReader({ project, busy, action, initialDocument, source, modelConfigured, settings }: Props) {
  const [documentId, setDocumentId] = useState(initialDocument || project.documents[0]?.id || '');
  const doc = project.documents.find(d => d.id === documentId) || project.documents[0];
  const [reading, setReading] = useState<PaperReading | null>(null);
  const [section, setSection] = useState('insight');
  const [view, setView] = useState('notes');
  const [draft, setDraft] = useState<ReadingEntry | null>(null);
  const [spanId, setSpanId] = useState('');
  const [quote, setQuote] = useState('');
  const [kind, setKind] = useState('note');
  const [note, setNote] = useState('');
  const [undo, setUndo] = useState<ReadingAnnotation | null>(null);
  const [removedEntry, setRemovedEntry] = useState<ReadingEntry | null>(null);
  const [startPage, setStartPage] = useState(1);
  const [endPage, setEndPage] = useState(doc?.pages || 1);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const selectedSpan = doc?.spans.find(s => s.id === spanId);
  const base = `/projects/${project.id}/paper-readings/${doc?.id}`;
  useEffect(() => {
    let live = true;
    setReading(null); setDraft(null); setSpanId(''); setQuote(''); setUndo(null); setRemovedEntry(null); setWarnings([]); setLoadError('');
    setStartPage(1); setEndPage(doc?.pages || 1);
    if (doc) api(`/projects/${project.id}/paper-readings/${doc.id}`).then(data => { if (live) setReading(data); }).catch(error => { if (live) setLoadError(error.message || '精读记录读取失败'); });
    return () => { live = false; };
  }, [project.id, doc?.id, reload]);
  if (!doc) return <div className="empty"><BookOpen size={34}/><h3>先导入一篇全文</h3><p>在文献库添加PDF、文本或Markdown，再建立带原文定位的精读笔记。</p></div>;
  const currentSection = sections.find(s => s.id === section)!;
  const entries = reading?.entries.filter(e => e.section === section) || [];
  const selectPassage = (sid: string, text?: string) => {
    if (!sid) { setSpanId(''); setQuote(''); setNote(''); return; }
    const span = doc.spans.find(s => s.id === sid);
    if (!span) return;
    setSpanId(sid); setQuote(text || span.text); setNote('');
  };
  const saveEntry = () => {
    if (!draft || !reading) return;
    const next = reading.entries.some(e => e.id === draft.id) ? reading.entries.map(e => e.id === draft.id ? draft : e) : [...reading.entries, draft];
    action('reading-save', async () => { setReading(await api(base, { method: 'PUT', body: JSON.stringify({ goal: reading.goal, entries: next }) })); setDraft(null); }, '精读条目与来源已保存');
  };
  const generate = () => action('reading-generate', async () => {
    const data = await post(base + '/generate', { goal: reading?.goal || 'reproduce', start_page: startPage, end_page: endPage });
    setReading(data); setWarnings(data.warnings || []);
  }, '精读草稿已追加保存，请逐项核对原文与推断');
  const annotate = () => action('reading-annotation', async () => {
    const data = await post(base + '/annotations', { span_id: spanId, quote, kind, note });
    setReading(data); setNote(''); setUndo(null);
  }, '批注已保存，反馈会用于下次辅助精读');
  const readSelection = (sid: string) => {
    const selection = window.getSelection();
    const parent = selection?.anchorNode?.parentElement?.closest('[data-reading-span]');
    const end = selection?.focusNode?.parentElement?.closest('[data-reading-span]');
    const text = selection?.toString();
    if (text && parent?.getAttribute('data-reading-span') === sid && end === parent) selectPassage(sid, text);
  };
  return <div className="paper-reader">
    <div className="reader-toolbar"><label>正在精读<select aria-label="精读文献" value={doc.id} disabled={!!busy || !!draft} onChange={e => setDocumentId(e.target.value)}>{project.documents.map(d => <option value={d.id} key={d.id}>{d.title}</option>)}</select></label><label>阅读目标<select aria-label="精读阅读目标" value={reading?.goal || 'reproduce'} disabled={!reading || !!busy || !!draft} onChange={e => action('reading-goal', async () => setReading(await api(base, { method: 'PUT', body: JSON.stringify({ goal: e.target.value, entries: reading?.entries || [] }) })))}><option value="concept">理解概念与直觉</option><option value="reproduce">动手复现与排错</option><option value="math">核对公式与推导</option></select></label><a className="button secondary" href={'/api' + base + '/export'}><Download size={15}/>导出精读包</a></div>
    <div className="reader-layout">
      <aside className="reading-index" aria-label="精读目录"><h2>阅读路径</h2><nav>{sections.map(s => <button key={s.id} className={section === s.id && view === 'notes' ? 'selected' : ''} disabled={!!draft} onClick={() => { setSection(s.id); setView('notes'); }}><span>{s.title}</span><small>{reading?.entries.filter(e => e.section === s.id).length || 0}</small></button>)}</nav><button className={'reader-original ' + (view === 'source' ? 'selected' : '')} disabled={!!draft} onClick={() => setView('source')}><FileText size={16}/>原文与批注<span>{reading?.annotations.length || 0}</span></button><div className="reading-progress"><BookOpen size={18}/><p>{doc.pages}页 · {doc.spans.length}段文字<br/>{reading?.entries.length || 0}条精读笔记</p></div><p className="reader-scope">{reading?.coverage.mode === 'model' ? `最近辅助读取：第${reading.coverage.start_page}—${reading.coverage.end_page}页。` : '手动精读，无模型生成结论。'}来源定位可核对，解释仍需作者判断。</p></aside>
      <section className="reading-canvas">
        {!reading ? loadError ? <div className="reading-empty" role="alert"><h3>精读记录暂时无法读取</h3><p>{loadError}</p><button className="button secondary" onClick={() => setReload(value => value + 1)}>重新读取</button></div> : <div className="page-loading"><LoaderCircle className="spin" size={20}/>正在读取精读记录…</div> : <>
          {view === 'notes' ? <><div className="reading-section-heading"><div><h2>{currentSection.title}</h2><p>{currentSection.question}</p></div><button className="button secondary" disabled={!!busy || !!draft || reading.entries.length >= 40} onClick={() => setDraft(freshEntry(section))}><Plus size={15}/>新增条目</button></div>
            {removedEntry && <button className="text-button" disabled={!!busy || !!draft || reading.entries.length >= 40} onClick={() => action('reading-entry-undo', async () => { setReading(await api(base, { method: 'PUT', body: JSON.stringify({ goal: reading.goal, entries: [...reading.entries, removedEntry] }) })); setRemovedEntry(null); }, '精读条目已恢复')}><Undo2 size={14}/>撤销移除条目</button>}
            {warnings.length > 0 && <div className="reading-warning" role="status">{warnings.map(w => <p key={w}>{w}</p>)}</div>}
            {draft && <div className="entry-editor"><div className="section-heading"><h3>{reading.entries.some(e => e.id === draft.id) ? '编辑精读条目' : '写下你的理解'}</h3><button className="icon-button" aria-label="取消编辑精读条目" disabled={!!busy} onClick={() => setDraft(null)}><X size={17}/></button></div><label className="first-label">条目标题<input aria-label="精读条目标题" value={draft.title} maxLength={120} disabled={!!busy} onChange={e => setDraft({ ...draft, title: e.target.value })}/></label><label>解释与推导<textarea aria-label="精读条目正文" value={draft.body} maxLength={8000} rows={7} disabled={!!busy} placeholder="写清问题、机制与具体例子。公式可写为 $x$ 或 $$x$$；示意数字注明示意。" onChange={e => setDraft({ ...draft, body: e.target.value })}/></label><label>证据等级<select aria-label="精读证据等级" value={draft.grade} disabled={!!busy} onChange={e => setDraft({ ...draft, grade: e.target.value })}>{Object.entries(grades).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>判断依据<textarea aria-label="精读判断依据" value={draft.rationale} maxLength={2000} rows={2} disabled={!!busy} placeholder="推断依靠什么；还需要核对什么？" onChange={e => setDraft({ ...draft, rationale: e.target.value })}/></label>{(section === 'bench' || section === 'limits' || draft.diagnostic || draft.cost) && <div className="bench-editor"><label>最低成本诊断<textarea aria-label="精读诊断方案" value={draft.diagnostic} maxLength={2000} rows={3} disabled={!!busy} onChange={e => setDraft({ ...draft, diagnostic: e.target.value })} placeholder="出现什么症状，先改哪个因素，观察什么量？"/></label><label>补丁与代价<textarea aria-label="精读补丁代价" value={draft.cost} maxLength={2000} rows={2} disabled={!!busy} onChange={e => setDraft({ ...draft, cost: e.target.value })}/></label></div>}<div className="editor-citations"><h4>关联原文片段</h4><p>将条目标为“原文有据”时至少关联一段；关联不等于解释已经正确。</p><select aria-label="精读条目引用片段" disabled={!!busy || draft.span_ids.length >= 8} value="" onChange={e => { if (e.target.value && !draft.span_ids.includes(e.target.value)) setDraft({ ...draft, span_ids: [...draft.span_ids, e.target.value] }); }}><option value="">选择需要核对的片段</option>{doc.spans.filter(s => !draft.span_ids.includes(s.id)).map(s => <option key={s.id} value={s.id}>第{s.page}页 · {s.id} · {s.text.slice(0, 38)}</option>)}</select>{draft.span_ids.map(sid => <div className="citation-row" key={sid}><button className="text-button" type="button" onClick={() => source(doc.id, sid)}>{sid} · 回看原文</button><button className="icon-button" type="button" aria-label={`取消条目引用${sid}`} disabled={!!busy} onClick={() => setDraft({ ...draft, span_ids: draft.span_ids.filter(s => s !== sid) })}><X size={14}/></button></div>)}</div><div className="note-actions"><button className="button primary" disabled={!!busy || !draft.title.trim() || draft.grade === 'stated' && !draft.span_ids.length || draft.span_ids.length > 8} onClick={saveEntry}><Check size={15}/>{busy === 'reading-save' ? '保存中…' : '保存精读条目'}</button><button className="button secondary" disabled={!!busy} onClick={() => setDraft(null)}>取消</button></div></div>}
            {entries.map(entry => <article className="reading-entry" key={entry.id}><div className="entry-meta"><span className={'evidence-grade ' + entry.grade}>{grades[entry.grade]}</span><button className="icon-button" aria-label={`编辑精读条目${entry.title}`} disabled={!!busy || !!draft} onClick={() => setDraft({ ...entry })}><Pencil size={15}/></button><button className="icon-button" aria-label={`移除精读条目${entry.title}`} disabled={!!busy || !!draft} onClick={() => action('reading-entry-remove', async () => { setReading(await api(base, { method: 'PUT', body: JSON.stringify({ goal: reading.goal, entries: reading.entries.filter(e => e.id !== entry.id) }) })); setRemovedEntry(entry); }, '精读条目已移除，可以撤销；已有研究设想保留')}><Trash2 size={15}/></button></div><h3>{entry.title}</h3><ReadingText text={entry.body}/>{entry.rationale && <p className="entry-rationale">判断依据：{entry.rationale}</p>}{(entry.diagnostic || entry.cost) && <div className="bench-note">{entry.diagnostic && <><h4>最低成本诊断</h4><ReadingText text={entry.diagnostic}/></>}{entry.cost && <><h4>补丁与代价</h4><ReadingText text={entry.cost}/></>}<p>诊断方案尚未执行，不作为实验结果。</p></div>}<div className="entry-sources">{entry.span_ids.map(sid => <button className="source-link" key={sid} onClick={() => source(doc.id, sid)}><Quote size={13}/>第{doc.spans.find(s => s.id === sid)?.page}页 · {sid}</button>)}{!entry.span_ids.length && <span>尚无关联原文片段</span>}</div><button className="text-button handoff-button" disabled={!!busy || !!draft || !!entry.note_id} onClick={() => action('reading-handoff', async () => { await post(base + '/entries/' + entry.id + '/research-note'); setReading(await api(base)); }, '已转为待验证的研究设想，可到总览继续设计实验')}><Lightbulb size={15}/>{entry.note_id ? '已转为研究设想' : '转为研究设想'}<ArrowRight size={13}/></button></article>)}
            {!entries.length && !draft && <div className="reading-empty"><BookOpen size={28}/><h3>让理解带着依据留下来</h3><p>{currentSection.question}</p><p>先从右侧原文选一段核对，再写下你的解释。没有依据的部分标为推断或猜测。</p><button className="text-button" onClick={() => setView('source')}>先阅读提取的原文<ArrowRight size={14}/></button></div>}
          </> : <><div className="reading-section-heading"><div><h2>原文与批注</h2><p>选择文字记录反馈，也可按段落添加；原文始终保留。</p></div>{doc.has_original && <a className="button secondary" href={`/api/projects/${project.id}/documents/${doc.id}/original`} target="_blank" rel="noreferrer">打开原文件</a>}</div><p className="reader-limit">当前展示提取文字。图表图像、公式和扫描内容请对照原文件，系统没有自动读取图像中的结果。</p><div className="reading-source-text">{doc.spans.map(span => <article key={span.id} className={spanId === span.id ? 'selected' : ''}><div className="passage-heading"><span>第{span.page}页 · {span.id}</span><button className="text-button" onClick={() => selectPassage(span.id)}><MessageSquareText size={14}/>批注此段</button></div><p data-reading-span={span.id} onMouseUp={() => readSelection(span.id)}>{span.text}</p>{reading.annotations.filter(a => a.span_id === span.id).map(a => <div className={'inline-annotation ' + a.kind} key={a.id}><span>{feedbackKinds[a.kind]}</span><p>“{a.quote}”{a.note ? '\n' + a.note : ''}</p></div>)}</article>)}</div></>}
        </>}
      </section>
      <aside className="reading-margin"><section><div className="section-heading"><h2>原文与反馈</h2><MessageSquareText size={17}/></div><p className="caption">重点不等于已懂。只有你明确标记，才记录为已理解。</p><label>选择原文片段<select aria-label="批注原文片段" disabled={!!busy} value={spanId} onChange={e => selectPassage(e.target.value)}><option value="">先选一段原文</option>{doc.spans.map(s => <option key={s.id} value={s.id}>第{s.page}页 · {s.id} · {s.text.slice(0, 24)}</option>)}</select></label>{selectedSpan && <><p className="annotation-excerpt">{selectedSpan.text}</p><label>批注引文<textarea aria-label="批注引文" value={quote} rows={3} maxLength={1600} disabled={!!busy} onChange={e => setQuote(e.target.value)}/></label><label>反馈类型<select aria-label="阅读反馈类型" value={kind} disabled={!!busy} onChange={e => setKind(e.target.value)}>{Object.entries(feedbackKinds).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><label>我的笔记<textarea aria-label="阅读批注内容" value={note} maxLength={2000} rows={3} disabled={!!busy} onChange={e => setNote(e.target.value)} placeholder="哪一步没懂，或你准备怎样核对？"/></label><button className="button secondary annotation-save" disabled={!!busy || !quote.trim() || !selectedSpan.text.includes(quote)} onClick={annotate}><Check size={14}/>{busy === 'reading-annotation' ? '保存中…' : '保存阅读批注'}</button><button className="text-button" onClick={() => source(doc.id, spanId)}>回看全文位置<ArrowRight size={13}/></button></>}
        {reading?.annotations.length ? <div className="annotation-list"><h3>已保存的反馈</h3>{reading.annotations.map(a => <article key={a.id}><div><b>{feedbackKinds[a.kind]}</b><span>{a.span_id}</span><button className="icon-button" aria-label={`移除批注${a.id}`} disabled={!!busy} onClick={() => action('reading-annotation-remove', async () => { const removed = await api(base + '/annotations/' + a.id, { method: 'DELETE' }); setUndo(removed); setReading(await api(base)); }, '批注已移除，可以撤销')}><Trash2 size={13}/></button></div><button className="annotation-quote" onClick={() => { selectPassage(a.span_id, a.quote); setNote(a.note); setKind(a.kind); }}>{a.quote}</button>{a.note && <p>{a.note}</p>}</article>)}</div> : <p className="margin-empty">尚无批注。选择原文后，可以标记重点、不懂或已懂。</p>}{undo && <button className="text-button" disabled={!!busy} onClick={() => action('reading-annotation-undo', async () => { setReading(await post(base + '/annotations', undo)); setUndo(null); }, '批注已恢复')}><Undo2 size={14}/>撤销移除</button>}</section>
        <section className="model-reading-tools"><div className="section-heading"><h2>辅助精读</h2><SearchCheck size={17}/></div><p className="caption">按本次页范围和已保存反馈追加草稿。现有笔记保留，解释与引文需要人工核对。</p><div className="form-grid"><label>起始页<input aria-label="辅助精读起始页" type="number" min={1} max={doc.pages} value={startPage} disabled={!!busy} onChange={e => setStartPage(Number(e.target.value))}/></label><label>结束页<input aria-label="辅助精读结束页" type="number" min={1} max={doc.pages} value={endPage} disabled={!!busy} onChange={e => setEndPage(Number(e.target.value))}/></label></div><button className="button primary" disabled={!!busy || !!draft || !reading || !modelConfigured || reading.entries.length >= 40 || !Number.isInteger(startPage) || !Number.isInteger(endPage) || startPage < 1 || endPage > doc.pages || startPage > endPage} onClick={generate}>{busy === 'reading-generate' ? <LoaderCircle size={15} className="spin"/> : <SearchCheck size={15}/>}生成精读草稿</button>{!modelConfigured && <button className="text-button" onClick={settings}><Settings size={14}/>配置模型服务</button>}<p className="reader-privacy">所选原文与批注会发送到你配置的模型。单次最多60000字符，超限需缩小范围；不会静默截断。</p></section>
      </aside>
    </div>
  </div>;
}

function ReadingText({ text }: { text: string }) {
  return <div className="reading-prose">{text.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g).map((part, i) => {
    if (!part.startsWith('$') || !part.endsWith('$') || part.length < 3) return <span key={i}>{part}</span>;
    const display = part.startsWith('$$');
    const formula = part.slice(display ? 2 : 1, display ? -2 : -1);
    return <span key={i} className={display ? 'reading-equation' : 'reading-inline-math'} dangerouslySetInnerHTML={{ __html: katex.renderToString(formula, { displayMode: display, throwOnError: false, trust: false, strict: 'ignore', maxExpand: 1000, maxSize: 20 }) }}/>;
  })}</div>;
}
