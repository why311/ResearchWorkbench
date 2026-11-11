import { useEffect, useState } from 'react';
import { api, post, type DeliveryProps, type ModuleProps, type Run } from './api';
import { SyncModule } from './SyncModule';
import './experiment-workspace.css';
import './delivery.css';

type ReportList = { id: string; title: string }[];

export function DeliveryWorkspace({ project, source }: {
  project: ModuleProps['project'] & { name: string };
  source: (did: string, sid?: string) => void;
}) {
  const [data, setData] = useState<{ reports: ReportList; runs: Run[]; drafts: ReportList } | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [opened, setOpened] = useState(false);
  const path = `/projects/${project.id}`;

  const refresh = async () => {
    const [reports, experiments, drafts] = await Promise.all([
      api(path + '/reports'), api(path + '/experiment-workspace'), api(path + '/writing-drafts'),
    ]);
    setData({ reports, runs: experiments.runs, drafts });
  };

  const action: DeliveryProps['action'] = async (key, task, message) => {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      await task();
      if (['save-report', 'generate-report', 'import-draft'].includes(key)) await refresh();
      if (message) setNotice(message);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy('');
    }
  };

  return <details className="literature experiment-workspace delivery" onToggle={event => {
    if (event.currentTarget.open && !opened) {
      setOpened(true);
      void action('load', refresh);
    }
  }}>
    <summary>成果同步与导出</summary>
    <div className="page-actions">
      <button disabled={!!busy} onClick={() => action('refresh-delivery', refresh)}>刷新运行与文稿</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!data && busy && <p role="status">正在读取成果文稿…</p>}
    {data && <SyncModule project={{ ...project, reports: data.reports, runs: data.runs }}
      drafts={data.drafts} busy={busy} action={action} source={source} />}
  </details>;
}

export function ModelSettings({ onSaved }: { onSaved: () => void }) {
  const [administrator, setAdministrator] = useState(false);
  const [configuration, setConfiguration] = useState({ base_url: '', model: '', has_key: false });
  const [key, setKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    api('/session').then(async session => {
      if (!live || !session.administrator) return;
      setAdministrator(true);
      const value = await api('/settings');
      if (live) { setConfiguration(value); setReady(true); }
    }).catch(err => { if (live) setError(err.message); });
    return () => { live = false; };
  }, []);

  const handle = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setStatus('');
    try { await operation(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  if (!administrator) return error ? <p role="alert">{error}</p> : null;

  return <details className="model-settings delivery">
    <summary>模型设置</summary>
    {error && <p role="alert">{error}</p>}
    {status && <p role="status">{status}</p>}
    {ready && <form onSubmit={event => {
      event.preventDefault();
      void handle(async () => {
        const { base_url, model } = configuration;
        setConfiguration(await api('/settings', {
          method: 'PUT', body: JSON.stringify({ base_url, model, api_key: key, clear_key: clearKey }),
        }));
        setKey('');
        setClearKey(false);
        setStatus('设置已保存');
        onSaved();
      });
    }}>
      <label>兼容 Chat Completions 的基础地址<input type="url" value={configuration.base_url} maxLength={1000}
        onChange={event => setConfiguration({ ...configuration, base_url: event.target.value })} /></label>
      <label>模型名称<input value={configuration.model} maxLength={200}
        onChange={event => setConfiguration({ ...configuration, model: event.target.value })} /></label>
      <label>API 密钥<input type="password" autoComplete="new-password" disabled={clearKey}
        maxLength={4096} value={key} onChange={event => setKey(event.target.value)} /></label>
      {configuration.has_key && <label className="key-option"><input type="checkbox" checked={clearKey}
        onChange={event => setClearKey(event.target.checked)} />清除已保存的密钥</label>}
      <div className="page-actions">
        <button className="primary" disabled={busy}>保存设置</button>
        <button type="button" disabled={busy} onClick={() => handle(async () => {
          const result = await post('/settings/test');
          setStatus(result.ok ? '已连接模型服务' : '服务已响应，请核对模型配置');
        })}>测试已保存的配置</button>
      </div>
    </form>}
  </details>;
}
