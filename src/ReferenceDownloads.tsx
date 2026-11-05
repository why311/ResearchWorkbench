import { useEffect, useState } from 'react';
import { api, post, type ModuleProps } from './api';

const states:Record<string,string>={pending:'等待处理',searching:'查找与下载',needs_selection:'请选择题录',not_found:'未找到开放全文',failed:'失败，可重试',imported:'已导入',queued:'排队中',running:'处理中',completed:'本轮完成',cancelled:'已停止',interrupted:'服务中断'};
export default function ReferenceDownloads({project,busy,action}:ModuleProps){
 const [queries,setQueries]=useState(''),[jobs,setJobs]=useState<any[]>([]),[revision,setRevision]=useState(0),[error,setError]=useState('');
 const [choices,setChoices]=useState<Record<string,string>>({});
 const base=`/projects/${project.id}`;
 useEffect(()=>{let live=true;let timer:ReturnType<typeof setTimeout>;setJobs([]);setError('');
  async function load(){try{const value=await api(base+'/reference-downloads');if(!live)return;setJobs(value);if(value.some((j:any)=>['queued','running'].includes(j.status)))timer=setTimeout(load,1500);}catch(e){if(live)setError((e as Error).message);}}
  load();return()=>{live=false;clearTimeout(timer);};
 },[base,revision]);
 const lines=queries.split('\n').map(q=>q.trim()).filter(Boolean);
 return <section className="completion-workspace reference-download-workspace"><form onSubmit={e=>{e.preventDefault();action('reference-batch',async()=>{await post(base+'/reference-downloads',{queries:lines});setRevision(n=>n+1);});}}><h2>批量获取参考文献</h2><label>题名、引用或arXiv编号，每行一条<textarea rows={6} required disabled={!!busy} value={queries} onChange={e=>setQueries(e.target.value)} placeholder="Attention Is All You Need&#10;arXiv:1706.03762v7"/></label><div className="ask-action"><span className="caption">{lines.length}/20条</span><button className="button primary" disabled={!!busy||!lines.length||lines.length>20}>查找并下载</button></div><p className="caption">题名精确匹配时导入；有歧义时选择题录。仅下载arXiv与NLM PMC开放数据中的PDF，保留来源和许可。其他全文可手动导入。</p></form>
 {error&&<p className="feedback error" role="alert">{error}<button className="text-button" onClick={()=>setRevision(n=>n+1)}>重新读取</button></p>}
 <div className="section-heading"><h2>下载记录</h2><button className="button secondary" disabled={!!busy} onClick={()=>action('refresh-downloads',async()=>setRevision(n=>n+1))}>刷新文献库与记录</button></div>
 {!jobs.length&&!error&&<p className="empty-text">粘贴题名或从文献读取引用列表，开始第一批下载。</p>}
 {jobs.map(job=><details className="download-batch" open key={job.id}><summary>{new Date(job.created).toLocaleString('zh-CN')} {states[job.status]}，{job.items.filter((i:any)=>i.status==='imported').length}/{job.items.length}已导入</summary>{['queued','running'].includes(job.status)&&<button className="button secondary" disabled={!!busy} onClick={()=>action('stop-downloads',async()=>{await post(base+'/reference-downloads/'+job.id+'/cancel');setRevision(n=>n+1);})}>停止后续下载</button>}<ol className="download-items">{job.items.map((item:any,index:number)=>{const key=job.id+index;return <li key={index}><div className="download-item-title"><h3>{item.query}</h3><span className={'badge '+(item.status==='imported'?'succeeded':'neutral')}>{states[item.status]}</span></div>{item.error&&<p role="alert">{item.error}</p>}{item.warnings?.map((w:string,i:number)=><p className="caption" key={i}>{w}</p>)}{item.status==='imported'?<p className="caption">原件已进入文献库；PDF解析进度见“文档结构”。</p>:!['queued','running'].includes(job.status)&&<div className="completion-toolbar">{item.candidates?.length>0&&<label>候选题录<select aria-label={`第${index+1}条候选题录`} value={choices[key]||''} onChange={e=>setChoices({...choices,[key]:e.target.value})}><option value="">重新检索</option>{item.candidates.map((c:any)=><option key={c.key} value={c.key}>{c.title} ({c.key})</option>)}</select></label>}<button className="button secondary" disabled={!!busy} onClick={()=>action('retry-reference',async()=>{await post(`${base}/reference-downloads/${job.id}/retry`,{index,candidate_key:choices[key]||''});setRevision(n=>n+1);})}>{choices[key]?'导入所选全文':'重试这一条'}</button></div>}</li>;})}</ol></details>)}
 </section>;
}
