import { useEffect, useState } from 'react';
import { api, type ExperimentProps, type ExperimentRecords, type ModuleProps } from './api';
import Reproduce from './Reproduce';
import SeriesPanel from './SeriesPanel';
import { AnalysisModule } from './AnalysisModule';
import './experiment-workspace.css';

const tabs = [
  ['reproduce', '实验复现'], ['series', '批量对照'], ['analysis', '数据分析'],
] as const;
type Tab = typeof tabs[number][0];

export default function ExperimentWorkspace({ context, source }: {
  context: ModuleProps['project']; source: (did: string) => void;
}) {
  const [tab, setTab] = useState<Tab>('reproduce');
  const [records, setRecords] = useState<ExperimentRecords | null>(null);
  const [status, setStatus] = useState({ docker: false, image_ready: false });
  const [run, setRun] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const path = `/projects/${context.id}/experiment-workspace`;
  const running = records?.runs.some(item => item.status === 'queued' || item.status === 'running') ||
    records?.experiment_series.some(item => item.status === 'queued' || item.status === 'running');

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const value = await api(path);
        if (live) setRecords(value);
      } catch (err) {
        if (live) setError((err as Error).message);
      } finally {
        if (live && running) timer = setTimeout(load, 1600);
      }
    };
    void load();
    return () => { live = false; clearTimeout(timer); };
  }, [path, running]);

  useEffect(() => {
    let live = true;
    api('/runtime/status').then(value => { if (live) setStatus(value); })
      .catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, []);

  const refreshStatus = async () => setStatus(await api('/runtime/status'));
  const action: ExperimentProps['action'] = async (key, task, message) => {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      await task();
      setRecords(await api(path));
      if (message) setNotice(message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy('');
    }
  };

  const props = records && { project: { ...context, ...records }, busy, action };
  return <section className="literature experiment-workspace">
    <h2>实验与分析</h2>
    <nav className="page-actions" aria-label="实验与分析工具">
      {tabs.map(([id, label]) => <button key={id} aria-pressed={tab === id} disabled={!!busy}
        onClick={() => { setTab(id); setError(''); setNotice(''); }}>{label}</button>)}
      <button disabled={!!busy} onClick={() => action('runtime-status', refreshStatus)}>刷新运行环境</button>
    </nav>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!props && !error && <p role="status">正在读取实验记录…</p>}
    {props && tab === 'reproduce' && <Reproduce key={run} {...props} status={status} refreshStatus={refreshStatus}
      initialRun={run} source={source} goRead={() => document.getElementById('project-documents')?.scrollIntoView()} />}
    {props && tab === 'series' && <SeriesPanel {...props} inspect={item => { setRun(item.id); setTab('reproduce'); }} />}
    {props && tab === 'analysis' && <AnalysisModule {...props} />}
  </section>;
}
