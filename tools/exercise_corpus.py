"""Exercise import queues and original-page endpoints using the supplied corpus."""
import json
from pathlib import Path
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/validation/corpus-workflow.json'
measurements=json.loads((ROOT/'output/validation/official-pdfs.json').read_text(encoding='utf-8'))
with httpx.Client(base_url='http://127.0.0.1:8787/api',trust_env=False,timeout=45) as client:
    def request(method,path,**kw):
        response=client.request(method,path,**kw)
        response.raise_for_status()
        return response.json()
    if OUT.exists():
        report=json.loads(OUT.read_text(encoding='utf-8'))
    else:
        pid=request('POST','/projects',json={'name':'验收 · 官方教材、扫描件与20篇论文','question':'核对真实文件导入、末页阅读与项目内引用关系'})['id']
        report={'project_id':pid,'documents':[]}
    pid=report['project_id'];base='/projects/'+pid
    def save():OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    pending=[r['file'] for r in measurements['results'] if r['file'] not in {d['file'] for d in report['documents']}]
    started=time.monotonic()
    while pending or any(d.get('status') in ('queued','running') for d in report['documents']):
        active=0
        for doc in report['documents']:
            if doc.get('status') not in ('queued','running'):
                continue
            state=request('GET',base+'/document-ingestions/'+doc['job_id'])
            doc.update(status=state['status'],completed=state['completed'],pages=state['total'],error=state['error'])
            if state['status'] in ('queued','running'):active+=1
            elif state['status']=='completed':
                t=time.monotonic();last=request('GET',base+'/documents/'+doc['document_id']+'/spans',params={'page':state['total']})
                doc.update(last_page_spans=last['total'],last_page_request_ms=round((time.monotonic()-t)*1000,2))
                print(doc['file'],doc['status'],doc['pages'],flush=True)
        while pending and active<4:
            filename=pending.pop(0)
            with (ROOT.parent/'pdf'/filename).open('rb') as stream:
                state=request('POST',base+'/document-ingestions',files={'file':(filename,stream,'application/pdf')})
            report['documents'].append({'file':filename,'document_id':state['document_id'],'job_id':state['id'],'status':state['status']})
            active+=1
        save()
        if time.monotonic()-started>1500:
            raise TimeoutError('workflow measurement timed out; recorded progress retained')
        time.sleep(1)
    report['seconds']=round(time.monotonic()-started,2)
    save()
