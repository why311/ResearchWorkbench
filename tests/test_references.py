from backend import references
from tests.test_documents import client, project


def add(client,pid,text):
    return client.post(f'/api/projects/{pid}/documents',files={'file':('references.txt',text.encode())}).json()['id']


def test_extract_confirm_link_export_and_isolation(client):
    pid,other=project(client),project(client)
    did=add(client,pid,'References\n[1] doi:10.1234/ABC(2).\n[2] arXiv:2301.12345v2.')
    target=add(client,pid,'Target text')
    foreign=add(client,other,'Other project text')
    base=f'/api/projects/{pid}'
    path=base+f'/documents/{did}/references-extract'
    assert client.post(path,json={'start_page':1,'end_page':1}).json()['created']==2
    rows=client.get(base+'/reference-network').json()['references']
    assert {r['identifier'] for r in rows}=={'doi:10.1234/abc(2)','arxiv:2301.12345'}
    assert all(r['status']=='candidate' and r['source']=={'page':1,'offset':0} for r in rows)
    rid=rows[0]['id']
    body={'label':'Named paper','status':'confirmed','target_document_id':target}
    assert client.put(base+'/references/'+rid,json={**body,'target_document_id':foreign}).status_code==404
    assert client.put(base+'/references/'+rid,json={**body,'target_document_id':did}).status_code==422
    assert client.put(base+'/references/'+rid,json=body).status_code==200
    assert client.post(path,json={'start_page':1,'end_page':1}).json()['created']==0
    kept=next(r for r in client.get(base+'/reference-network/export').json()['references'] if r['id']==rid)
    assert kept['status']=='confirmed' and kept['target_document_id']==target and kept['quote']==rows[0]['quote']
    outsider=f'/api/projects/{other}'
    assert client.get(outsider+'/reference-network').json()['references']==[]
    assert client.put(outsider+'/references/'+rid,json=body).status_code==404
    assert client.delete(outsider+'/references/'+rid).status_code==404
    assert client.post(outsider+f'/documents/{did}/references-extract',json={'start_page':1,'end_page':1}).status_code==404
    assert client.delete(base+'/references/'+rid).status_code==200
    assert len(client.get(base+'/reference-network').json()['references'])==1


def test_ranges_empty_labels_and_long_page_source(client):
    pid=project(client)
    text='\n\n'.join(f'Paragraph {i}' for i in range(104))+'\n\n[1] doi:10.5555/last.'
    did=add(client,pid,text)
    base=f'/api/projects/{pid}'
    path=base+f'/documents/{did}/references-extract'
    assert client.post(path,json={'start_page':2,'end_page':1}).status_code==422
    assert client.post(path,json={'start_page':1,'end_page':2}).status_code==422
    client.post(path,json={'start_page':1,'end_page':1})
    row=client.get(base+'/reference-network').json()['references'][0]
    assert row['source']=={'page':1,'offset':100}
    original=client.get(base+f'/documents/{did}?page=1&offset=100').json()['items']
    assert any(s['id']==row['span_id'] and row['quote'] in s['text'] for s in original)
    assert client.put(base+'/references/'+row['id'],json={'label':'  '}).status_code==422
    empty=add(client,pid,'No reference identifiers here.')
    assert client.post(base+f'/documents/{empty}/references-extract',json={'start_page':1,'end_page':1}).json()['found']==0


def test_identifier_normalization_and_budget(client):
    parsed=references.identifiers('doi:10.1234/Title(2)). arxiv.org/abs/hep-th/9901001v3; arXiv:2301.12345v5')
    assert [v[0] for v in parsed]==['doi:10.1234/title(2)','arxiv:hep-th/9901001','arxiv:2301.12345']
    pid=project(client)
    did=add(client,pid,'\n\n'.join(f'doi:10.5555/{i}' for i in range(301)))
    base=f'/api/projects/{pid}'
    assert client.post(base+f'/documents/{did}/references-extract',json={'start_page':1,'end_page':1}).status_code==422
    assert client.get(base+'/reference-network').json()['references']==[]
