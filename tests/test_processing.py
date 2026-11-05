import time
import pytest
from fastapi import HTTPException
from backend import app as core, ingestion, discovery, graph_insights, reference_downloads
from tests.test_documents import client, project, pdf


def test_real_pdf_queue_source_compatibility_and_original(client):
    pid=project(client)
    base=f'/api/projects/{pid}'
    content=pdf()
    response=client.post(base+'/document-ingestions',files={'file':('two-pages.pdf',content)})
    assert response.status_code==200, response.text
    record=response.json()
    end=time.monotonic()+45
    while time.monotonic()<end:
        record=client.get(base+'/document-ingestions/'+record['id']).json()
        if record['status'] not in {'queued','running'}:break
        time.sleep(.1)
    assert record['status']=='completed',record
    did=record['document_id']
    structured=client.get(base+f'/documents/{did}/spans?page=2').json()
    assert 'Second page conclusion.' in structured['items'][0]['text']
    sid=structured['items'][0]['id']
    assert client.get(base+f'/documents/{did}?page=2').json()['items'][0]['id']==sid
    assert client.get(base+f'/documents/{did}/original').content==content
    assert client.put(base+f'/documents/{did}/translations/{sid}',json={'text':'第二页结论。'}).status_code==200
    assert client.put(base+f'/documents/{did}/annotations',json={'span_id':sid,'note':'Retain page two'}).status_code==200
    other=project(client)
    assert client.get(f'/api/projects/{other}/document-ingestions/'+record['id']).status_code==404
    assert client.get(f'/api/projects/{other}/documents/{did}/spans').status_code==404


def test_scan_worker_uses_real_local_ocr(tmp_path):
    from backend import pdf_worker
    from PIL import Image, ImageDraw, ImageFont
    target=tmp_path/'scan.pdf'
    image=Image.new('RGB',(1000,500),'white')
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',36)
    draw.text((50,100),'SCANNED PAGE EVIDENCE 42',fill='black',font=font)
    image.save(target,'PDF');image.close()
    pages=[v for v in pdf_worker.extract(target,1,True) if v['type']=='page']
    assert pages[0]['method']=='ocr'
    assert 'EVIDENCE' in ' '.join(b['text'] for b in pages[0]['blocks']).upper()


def test_graph_only_confirmed_links_and_metadata_search(client,monkeypatch):
    pid=project(client);base=f'/api/projects/{pid}'
    did=client.post(base+'/documents',files={'file':('one.md',b'doi:10.1234/target')}).json()['id']
    target=client.post(base+'/documents',files={'file':('two.md',b'Target paper')}).json()['id']
    client.post(base+f'/documents/{did}/references-extract',json={'start_page':1,'end_page':1})
    row=client.get(base+'/reference-network').json()['references'][0]
    body={'label':'Target','target_document_id':target,'status':'candidate'}
    client.put(base+'/references/'+row['id'],json=body)
    assert client.get(base+'/graph-insights').json()['edges']==[]
    client.put(base+'/references/'+row['id'],json={**body,'status':'confirmed'})
    graph=client.get(base+'/graph-insights').json()
    assert graph['edges']==[{'source':did,'target':target}]
    assert abs(sum(n['pagerank'] for n in graph['nodes'])-1)<1e-8
    assert '-->' in client.get(base+'/graph-insights/mermaid').text
    monkeypatch.setattr(discovery,'public_json',lambda *a:{'message':{'items':[{'title':['Paper'],'DOI':'10.1234/example','author':[{'family':'Author'}]}]}})
    result=client.get('/api/literature/discover?q=seed').json()
    assert result['items'][0]['title']=='Paper' and result['provider']=='crossref'


def test_batch_isolation_retry_and_cancel(client,monkeypatch):
    monkeypatch.setattr(reference_downloads.POOL,'submit',lambda *a:None)
    pid=project(client);base=f'/api/projects/{pid}/reference-downloads'
    record=client.post(base,json={'queries':['arXiv:1706.03762']}).json()
    assert record['status']=='queued'
    assert client.post(base+'/'+record['id']+'/cancel').json()['status']=='cancelled'
    assert client.post(base+'/'+record['id']+'/retry',json={'index':0}).json()['status']=='queued'
    other=f'/api/projects/{project(client)}/reference-downloads'
    assert client.post(other+'/'+record['id']+'/cancel').status_code==404
    assert client.post(other+'/'+record['id']+'/retry',json={'index':0}).status_code==404
    with pytest.raises(HTTPException):reference_downloads.s3_read('https://example.com/foreign')

