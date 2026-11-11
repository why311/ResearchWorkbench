import { useEffect, useState } from 'react';
import { api, post, type ModuleProps } from './api';
import { EvidenceTasks } from './EvidenceTasks';
import SemanticSearch from './SemanticSearch';
import ResearchSynthesis from './ResearchSynthesis';
import './research-workspace.css';

const tabs = [
  ['semantic', '语义检索'], ['comparison', '证据比较'], ['agent', '研究任务'],
  ['synthesis', '综述与演进'], ['drafts', '开题与草稿'],
] as const;
type Tab = typeof tabs[number][0];
type Source = (did: string, sid?: string) => void;
type Draft = { id: string; title: string; template: string; citations: { alias: string; document_id: string; span_id: string }[] };
type Future = { document_id: string; id: string; page: number; title: string; text: string };

function WritingDrafts({ project, busy, action, source }: ModuleProps & { source: Source }) {
  const [idea, setIdea] = useState(project.question);
  const [selected, setSelected] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<Pick<Draft, 'id' | 'title'>[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [future, setFuture] = useState<Future[] | null>(null);
  const [error, setError] = useState('');
  const base = `/projects/${project.id}`;
  const path = base + '/writing-drafts';
  const refresh = async () => setDrafts(await api(path));

  useEffect(() => {
    let live = true;
    api(path).then(value => { if (live) setDrafts(value); })
      .catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [path]);

  return <div className="drafts">
    <form onSubmit={event => {
      event.preventDefault();
      void action('outline', async () => {
        setDraft(await post(base + '/literature-outline', { idea, document_ids: selected }));
        await refresh();
      }, '开题框架已保存');
    }}>
      <h3>开题框架</h3>
      <label>研究想法<textarea rows={3} maxLength={1000} value={idea} onChange={event => setIdea(event.target.value)} /></label>
      <fieldset><legend>引用全文（最多15篇）</legend>
        {project.documents.map(doc => <label key={doc.id}>
          <input type="checkbox" checked={selected.includes(doc.id)}
            disabled={!!busy || selected.length >= 15 && !selected.includes(doc.id)}
            onChange={event => setSelected(ids => event.target.checked ? [...ids, doc.id] : ids.filter(id => id !== doc.id))} />
          {doc.title}
        </label>)}
        {!project.documents.length && <p>先导入可引用的全文。</p>}
      </fieldset>
      <button className="primary" disabled={!!busy || !idea.trim() || !selected.length}>生成开题框架</button>
    </form>
    <div className="page-actions">
      <button disabled={!!busy} onClick={() => action('future', async () => {
        const result = await api(base + '/future-work');
        setFuture(result.items);
      })}>查看文献展望原文</button>
    </div>
    {future && (future.length ? <details open><summary>展望候选</summary>{future.map(item => <article key={`${item.document_id}:${item.id}`}>
      <p>{item.text}</p>
      <button onClick={() => source(item.document_id, item.id)}>{item.title} · 第{item.page}页</button>
    </article>)}</details> : <p>本项目暂未找到展望段落。</p>)}
    <label>已保存的草稿<select disabled={!!busy} value={draft?.id ?? ''} onChange={event => {
      const id = event.target.value;
      if (id) void action('load-draft', async () => setDraft(await api(path + '/' + id)));
      else setDraft(null);
    }}>
      <option value="">选择草稿</option>
      {drafts.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
    </select></label>
    {error && <p role="alert">{error}</p>}
    {draft && <form onSubmit={event => {
      event.preventDefault();
      void action('save-draft', async () => {
        setDraft(await api(path + '/' + draft.id, {
          method: 'PUT', body: JSON.stringify({ title: draft.title, template: draft.template }),
        }));
        await refresh();
      }, '草稿已保存');
    }}>
      <label>标题<input required maxLength={100} value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} /></label>
      <label>Markdown 正文<textarea required rows={16} maxLength={200000} value={draft.template} onChange={event => setDraft({ ...draft, template: event.target.value })} /></label>
      <div className="page-actions">
        <button className="primary" disabled={!!busy}>保存草稿</button>
        <a href={`/api${path}/${draft.id}/export`}>导出已保存的 Markdown</a>
      </div>
      {draft.citations.length > 0 && <details><summary>引用来源</summary>
        <ul>{draft.citations.map(citation => <li key={citation.alias}>
          <button type="button" onClick={() => source(citation.document_id, citation.span_id)}>
            {citation.alias} · {project.documents.find(doc => doc.id === citation.document_id)?.title} · {citation.span_id}
          </button>
        </li>)}</ul>
      </details>}
    </form>}
  </div>;
}

export default function ResearchWorkspace({ project, source, modelRevision }: { project: ModuleProps['project']; source: Source; modelRevision: number }) {
  const [tab, setTab] = useState<Tab>('semantic');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [configured, setConfigured] = useState(false);

  useEffect(() => {
    let live = true;
    api('/research-model-status').then(result => { if (live) setConfigured(result.configured); })
      .catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [modelRevision]);

  const action: ModuleProps['action'] = async (key, task, success) => {
    setBusy(key);
    setError('');
    setNotice('');
    try { await task(); if (success) setNotice(success); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(''); }
  };
  const props = { project, source, busy, action };

  return <section className="literature research-workspace">
    <h2>研究与写作</h2>
    <nav className="page-actions" aria-label="研究与写作工具">
      {tabs.map(([id, title]) => <button key={id} aria-pressed={tab === id} disabled={!!busy}
        onClick={() => { setTab(id); setError(''); setNotice(''); }}>{title}</button>)}
    </nav>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {tab === 'semantic' && <SemanticSearch {...props} />}
    {(tab === 'comparison' || tab === 'agent') && <EvidenceTasks key={tab} kind={tab} modelConfigured={configured} {...props} />}
    {tab === 'synthesis' && <>
      {!configured && <p className="muted">生成综述、回应判断和流程图需要服务端模型配置。时间线可手动填写。</p>}
      <ResearchSynthesis {...props} />
    </>}
    {tab === 'drafts' && <WritingDrafts {...props} />}
  </section>;
}
