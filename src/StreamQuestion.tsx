import { useEffect, useRef, useState } from 'react';
import { BookOpen, Search, Square } from 'lucide-react';
import type { Answer, Evidence } from './api';

export default function StreamQuestion({projectId, documents, question, disabled, onAnswer, cite}:{projectId:string;documents:{id:string;title:string;filename?:string}[];question:string;disabled:boolean;onAnswer:(a:Answer)=>void;cite:(id:string)=>void}) {
  const [selected,setSelected]=useState('');
  const [value,setValue]=useState(question), [phase,setPhase]=useState(''), [draft,setDraft]=useState(''), [error,setError]=useState('');
  const [answer,setAnswer]=useState<Answer|null>(null);
  const controller=useRef<AbortController|null>(null);
  const sourceRef=useRef<Evidence[]>([]);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort();};},[]);
  const running=phase==='retrieving'||phase==='generating';
  async function submit() {
    const abort=new AbortController(); controller.current=abort;sourceRef.current=[];
    setPhase('retrieving');setDraft('');setError('');setAnswer(null);
    let sources:Evidence[]=[], raw='', finished=false;
    try {
      const response=await fetch(`/api/projects/${projectId}/evidence/stream`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:value,document_ids:selected?[selected]:[]}),signal:abort.signal});
      if(abort.signal.aborted)throw new Error('已停止生成');
      if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||'请求失败，请重试');}
      if(!response.body)throw new Error('浏览器未提供响应流，请升级浏览器后重试');
      const reader=response.body.getReader(), decoder=new TextDecoder();let buffer='';
      while(true){
        const {done,value:chunk}=await reader.read();buffer+=decoder.decode(chunk,{stream:!done});
        if(abort.signal.aborted)throw new Error('已停止生成');
        if(controller.current!==abort||!alive.current)return;
        if(buffer.length>200000)throw new Error('响应过长，已停止，请缩小问题范围');
        const frames=buffer.split(/\r?\n\r?\n/);buffer=frames.pop()||'';
        for(const frame of frames){
          const lines=frame.split(/\r?\n/), event=lines.find(l=>l.startsWith('event:'))?.slice(6).trim();
          const text=lines.filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');
          if(!text)continue;const data=JSON.parse(text);
          if(event==='sources'){sources=data;sourceRef.current=data;onAnswer({mode:'extractive',answer:'正在根据这些原文生成草稿。',evidence:sources,claims:[]});}
          if(event==='delta'){
            setPhase('generating');raw+=data;
            if(raw.length>64000)throw new Error('模型草稿过长，请缩小问题范围');
            const visible=Array.from(raw.matchAll(/"text"\s*:\s*"((?:\\.|[^"\\])*)(?:"|$)/g)).map(m=>{try{return JSON.parse('"'+m[1]+'"');}catch{return '';}}).join('\n\n');
            setDraft(visible.slice(0,16000));
          }
          if(event==='error')throw new Error(data);
          if(event==='result'){finished=true;setAnswer(data);onAnswer(data);setDraft('');setPhase('done');}
        }
        if(done)break;
      }
      if(!finished)throw new Error('连接提前结束，草稿未保存为结论，请重试');
    }catch(e){
      if(!alive.current||controller.current!==abort)return;
      setDraft('');
      if(abort.signal.aborted){setPhase('cancelled');onAnswer({mode:'extractive',answer:'已停止生成，仅保留检索原文。',evidence:sources,claims:[]});}else{setPhase('failed');setError((e as Error).message);}
      if(!abort.signal.aborted)onAnswer({mode:'extractive',answer:'生成未完成，请查看原文或重试。',evidence:sources,claims:[]});
    }finally{if(controller.current===abort)controller.current=null;}
  }
  function stop(){controller.current?.abort();setPhase('cancelled');setDraft('');setAnswer(null);onAnswer({mode:'extractive',answer:'已停止生成，仅保留检索原文。',evidence:sourceRef.current,claims:[]});}
  return <section className="surface question-workspace"><div className="section-heading"><h2>向项目资料提问</h2></div><form onSubmit={e=>{e.preventDefault();submit();}}><label>检索范围<select value={selected} disabled={running||disabled} onChange={e=>setSelected(e.target.value)}><option value="">全部项目文献</option>{documents.map(d=><option value={d.id} key={d.id}>{d.title}{d.filename?' ('+d.filename+')':''}</option>)}</select></label><label>研究问题<textarea rows={4} required minLength={2} maxLength={2000} disabled={running||disabled} value={value} onChange={e=>setValue(e.target.value)} placeholder="例如：Adam参数和训练使用的GPU是什么？"/></label><div className="ask-action"><span className="caption">当前项目全文</span>{running?<button key="stop" type="button" className="button secondary" onClick={e=>{e.preventDefault();stop();}}><Square size={15}/>停止生成</button>:<button key="submit" type="submit" className="button primary" disabled={disabled||value.trim().length<2}><Search size={16}/>查找并回答</button>}</div></form>
    {running&&<div className="stream-preview"><p role="status">{phase==='retrieving'?'正在检索原文…':'正在生成草稿，尚未完成引文核对…'}</p>{draft&&<p className="stream-draft">{draft}</p>}</div>}
    {phase==='cancelled'&&<p role="status" className="note">已停止生成。未完成草稿未保存，原文仍可查看。</p>}
    {error&&<p role="alert" className="feedback error">{error}</p>}
    {answer&&<div className="answer"><p>{answer.answer}</p>{answer.claims.map((claim,i)=><div className="claim" key={i}><p>{claim.text}</p><div>{claim.citations.map((c,j)=><button className="source-link" key={c} onClick={()=>cite(c)}><BookOpen size={12}/>依据{j+1}</button>)}</div></div>)}</div>}
  </section>;
}
