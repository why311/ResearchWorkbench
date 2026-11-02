import { useEffect, useState } from 'react';
import { api } from './api';

type Segment = {id:string;page:number;text:string;translation:{text:string;method:string;reviewed:boolean}|null};
type Page = {items:Segment[];has_more:boolean;total:number};
export default function ParallelReading({projectId,documents}:{projectId:string;documents:{id:string;title:string;pages:number}[]}) {
  const [did,setDid]=useState(''),[language,setLanguage]=useState('zh'),[page,setPage]=useState(1),[offset,setOffset]=useState(0);
  const [data,setData]=useState<Page|null>(null),[error,setError]=useState(''),[notice,setNotice]=useState(''),[revision,setRevision]=useState(0);
  const [editing,setEditing]=useState(''),[text,setText]=useState(''),[reviewed,setReviewed]=useState(false),[busy,setBusy]=useState(false);
  const doc=documents.find(d=>d.id===did),base=`/projects/${projectId}/documents/${did}`;
  const query=`?language=${language}&page=${page}&offset=${offset}`;
  useEffect(()=>{let live=true;setData(null);setError('');setNotice('');if(did)api(base+'/translations'+query).then(v=>{if(live)setData(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[base,query,revision]);
  const locked=busy||!!editing;
  const save=async()=>{setBusy(true);setError('');try{await api(base+'/translations/'+editing,{method:'PUT',body:JSON.stringify({language,text,reviewed})});setEditing('');setRevision(n=>n+1);}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <section className="literature"><h2>双语对照阅读</h2>
    <label>文献<select value={did} disabled={locked} onChange={e=>{setDid(e.target.value);setPage(1);setOffset(0);}}><option value="">选择文献</option>{documents.map(d=><option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
    {doc&&<><div className="translation-controls"><label>译文<select disabled={locked} value={language} onChange={e=>{setLanguage(e.target.value);setOffset(0);}}><option value="zh">中文</option><option value="en">English</option></select></label><label>页码<input type="number" min={1} max={doc.pages} value={page} disabled={locked} onChange={e=>{const n=Number(e.target.value);if(Number.isInteger(n)&&n>=1&&n<=doc.pages){setPage(n);setOffset(0);}}}/></label></div>
      <div className="page-actions"><button disabled={locked||!data} onClick={async()=>{setBusy(true);setError('');setNotice('');try{const result=await api(base+'/translate',{method:'POST',body:JSON.stringify({language,page,offset})});setData(result);setNotice(result.warnings.join(' ')||'本页段译文已保存，请对照原文核对。');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?'处理中…':'翻译本页段'}</button><a href={'/api'+base+'/translations-export?language='+language}>导出双语包</a><button disabled={locked||!offset} onClick={()=>setOffset(n=>Math.max(0,n-40))}>上一组</button><button disabled={locked||!data?.has_more} onClick={()=>setOffset(n=>n+40)}>下一组</button></div>
      <p className="muted">翻译会把当前页段发送给已配置模型。已有译文保留；片段对应核对不代表翻译质量保证。</p>
      {notice&&<p role="status">{notice}</p>}{!data&&!error&&<p role="status">正在读取原文与译文…</p>}
      {data?.items.map(s=><div className="translation-row" key={s.id}><section><h3>原文 · 第{s.page}页 · {s.id}</h3><p>{s.text}</p></section><section><h3>{language==='zh'?'中文译文':'English translation'}</h3>{editing===s.id?<><label>编辑译文<textarea rows={6} maxLength={8000} disabled={busy} value={text} onChange={e=>{setText(e.target.value);setReviewed(false);}}/></label><label className="translation-reviewed"><input type="checkbox" disabled={busy} checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/>已对照原文核对</label><div className="page-actions"><button disabled={busy||!text.trim()} onClick={save}>保存译文</button><button disabled={busy} onClick={()=>setEditing('')}>取消</button></div></>:<><p>{s.translation?.text||'尚未填写译文。'}</p>{s.translation&&<p className="muted">{s.translation.method==='model'?'模型草稿':'人工保存'} · {s.translation.reviewed?'已核对':'待核对'}</p>}<button disabled={locked} onClick={()=>{setEditing(s.id);setText(s.translation?.text||'');setReviewed(!!s.translation?.reviewed);}}>编辑译文</button></>}</section></div>)}
      {data&&!data.items.length&&<p>本页段没有文字，请选择其他页码或返回上一组。</p>}
    </>}{error&&<p role="alert">{error}<button disabled={locked} onClick={()=>setRevision(n=>n+1)}>重新读取</button></p>}
  </section>;
}
