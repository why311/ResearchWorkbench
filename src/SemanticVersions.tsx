import { useEffect, useState } from 'react';
import { api, post } from './api';

export default function SemanticVersions({projectId,first,second,busy,action}:{projectId:string;first:string;second:string;busy:string;action:(key:string,fn:()=>Promise<any>,success?:string)=>Promise<void>}) {
 const [state,setState]=useState<any>(null),[result,setResult]=useState<any>(null),[error,setError]=useState('');
 const base=`/projects/${projectId}`;
 useEffect(()=>{let live=true;let timer:ReturnType<typeof setTimeout>;setState(null);setResult(null);setError('');
  async function load(){try{const value=await api(base+'/semantic-indexes');if(!live)return;setState(value);if(value.preparing||value.indexes.some((i:any)=>[first,second].includes(i.document_id)&&['queued','running'].includes(i.status)))timer=setTimeout(load,1500);}catch(e){if(live)setError((e as Error).message);}}
  load();return()=>{live=false;clearTimeout(timer);};
 },[base,first,second,busy]);
 const indices=[first,second].map(id=>state?.indexes.find((i:any)=>i.document_id===id));
 const ready=indices.every(i=>i?.status==='ready'&&i.model_revision===state?.revision);
 return <section className="semantic-version-check"><h3>语义版本核对</h3><div className="inline-actions">
 <button className="button secondary" disabled={!!busy||state?.preparing||state?.ready} onClick={()=>action('semantic-prepare',async()=>setState(await post('/semantic/prepare')))}>{state?.preparing?'正在准备模型…':state?.ready?'语义模型已就绪':'准备语义模型'}</button>
 <button className="button secondary" disabled={!!busy||!state?.ready||!second||indices.some(i=>['queued','running'].includes(i?.status))} onClick={()=>action('version-index',async()=>{for(const id of [first,second]){const old=state.indexes.find((i:any)=>i.document_id===id);if(old?.status!=='ready'||old.model_revision!==state.revision)await post(`${base}/documents/${id}/semantic-index`);}setState(await api(base+'/semantic-indexes'));})}>建立两篇语义索引</button>
 <button className="button primary" disabled={!!busy||!second||!ready} onClick={()=>action('semantic-versions',async()=>setResult(await post(base+'/semantic-duplicates',{document_ids:[first,second]})))}>比较正文语义</button></div>
 {indices.map((i,n)=>i&&<p className="caption" key={n}>{n===0?'当前文献':'对比文献'}：{({ready:'索引完成',queued:'排队中',running:'建立索引',failed:'索引失败',cancelled:'已停止',interrupted:'已中断'} as Record<string,string>)[i.status]} {i.completed}/{i.total} {i.error}</p>)}
 {(error||state?.error)&&<p role="alert">{error||state.error}</p>}
 {result&&<><p className="caption">{result.scope}</p>{result.pairs.map((p:any)=><div key={p.second_id}><p>{p.candidate?'发现语义相近版本候选':'未达到版本候选阈值'}，双向覆盖率 {(p.first_coverage*100).toFixed(1)}% / {(p.second_coverage*100).toFixed(1)}%</p>{p.examples.map((e:any,i:number)=><div className="completion-columns semantic-pair" key={i}><blockquote>{e.first}</blockquote><blockquote>{e.second}</blockquote></div>)}</div>)}</>}
 </section>;
}
