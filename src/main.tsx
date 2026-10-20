import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Project = { id: string; name: string; question: string };
function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState('');
  const [question, setQuestion] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
      const project = await response.json(); setProjects(old => [project, ...old]); setName(''); setQuestion('');
    } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  };
  return <main><header><span>研舟</span><p>把一个研究问题，变成持续积累的项目。</p></header><h1>研究项目</h1><p className="muted">当前版本提供项目管理骨架，科研功能按阶段加入。</p>{error && <div role="alert">{error}<button onClick={load}>重新读取</button></div>}<div className="workspace"><form onSubmit={create}><h2>开始一个项目</h2><label>项目名称<input aria-label="项目名称" required maxLength={100} value={name} onChange={e => setName(e.target.value)}/></label><label>研究问题<textarea aria-label="研究问题" rows={4} maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)}/></label><button className="primary" disabled={saving || !name.trim()}>{saving ? '保存中…' : '创建项目'}</button></form><section aria-label="项目列表">{loading ? <p role="status">正在读取项目…</p> : projects.length ? projects.map(p => <article key={p.id}><h2>{p.name}</h2><p>{p.question || '尚未填写研究问题'}</p></article>) : <p className="muted">还没有项目，可以从左侧创建。</p>}</section></div></main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
