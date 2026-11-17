import json

import pytest
from fastapi import HTTPException

from backend import app as core, semantic, streaming, reference_downloads as downloads, graph_insights
from backend.pdf_worker import order_ocr
from tests.test_workbench import client, create
from tests.test_semantic import local_model


def test_stream_final_checks_quotes_and_keeps_sources(client, monkeypatch):
    pid = create(client)
    hit = {'citation': 'd:p1-s1', 'document_id':'d','id':'p1-s1','page':1,'title':'Source','text':'The score is 0.8.'}
    monkeypatch.setattr(core, 'search_evidence', lambda *_: [hit])
    monkeypatch.setattr(core, 'settings', lambda: {'base_url':'https://example.test','model':'test','api_key':'private-test-key'})
    valid = {'text':'Reported score','citations':['d:p1-s1'],'quotes':['score is 0.8']}
    async def tokens(*_):
        output=json.dumps({'claims':[valid,{**valid,'quotes':['1.0']},{**valid,'citations':['foreign']}]})
        for i in range(0,len(output),9):
            yield output[i:i+9]
    monkeypatch.setattr(streaming, 'model_tokens', tokens)
    response=client.post(f'/api/projects/{pid}/evidence/stream',json={'question':'score'})
    assert response.status_code==200 and 'text/event-stream' in response.headers['content-type']
    assert response.text.count('event: delta')>5 and 'private-test-key' not in response.text
    frames=response.text.split('\n\n')
    result=json.loads(next(f for f in frames if f.startswith('event: result')).split('data: ',1)[1])
    assert len(result['claims'])==1 and result['claims'][0]['text']=='Reported score'
    assert result['evidence']==[hit]
    assert client.post(f'/api/projects/{pid}/evidence/stream',json={'question':'  '}).status_code==422
    async def broken(*_):
        yield '{"claims":'
        raise ValueError('must not leak provider body')
    monkeypatch.setattr(streaming, 'model_tokens', broken)
    failure=client.post(f'/api/projects/{pid}/evidence/stream',json={'question':'score'}).text
    assert 'event: error' in failure and 'event: result' not in failure and 'must not leak' not in failure


def test_semantic_versions_use_complete_real_index(client, local_model, monkeypatch):
    pid, other = create(client), create(client)
    texts=['The model uses a random seed of 42. The accuracy is 0.8.',
           'The model uses a random seed of 42. The accuracy is 0.81.',
           'Ancient galaxies emit light observed by a telescope. Stellar evolution is studied.']
    docs=[core.add_document(pid,str(i),'different-name-'+str(i)+'.txt',1,[{'id':'p1-s1','page':1,'text':t}]) for i,t in enumerate(texts)]
    monkeypatch.setattr(semantic.POOL,'submit',lambda *_:None)
    for d in docs:
        assert client.post(f'/api/projects/{pid}/documents/{d["id"]}/semantic-index').status_code==200
        semantic.build(pid,d['id'])
    ids=[d['id'] for d in docs]
    response=client.post(f'/api/projects/{pid}/semantic-duplicates',json={'document_ids':ids})
    assert response.status_code==200,response.text
    pairs=response.json()['pairs']
    assert {pairs[0]['first_id'],pairs[0]['second_id']}==set(ids[:2])
    assert pairs[0]['similarity']>pairs[-1]['similarity']
    assert pairs[0]['first_coverage']>=.5 and pairs[0]['second_coverage']>=.5
    assert all(len(p['examples'])>=1 for p in pairs)
    assert client.post(f'/api/projects/{other}/semantic-duplicates',json={'document_ids':ids[:2]}).status_code==404
    assert client.post(f'/api/projects/{pid}/semantic-duplicates',json={'document_ids':[ids[0],ids[0]]}).status_code==422


def test_reference_batch_partial_failure_choice_and_retry(client, monkeypatch):
    pid, other=create(client),create(client)
    monkeypatch.setattr(downloads.POOL,'submit',lambda *_:None)
    candidate={'key':'arxiv:1706.03762v7','arxiv_id':'1706.03762v7','title':'Attention','exact':True}
    def resolve(q):
        if q=='failure':raise HTTPException(502,'offline')
        return ([{**candidate,'exact':q=='exact'}] if q!='missing' else []),[]
    monkeypatch.setattr(downloads,'resolve',resolve)
    monkeypatch.setattr(downloads,'import_candidate',lambda pid,c:core.add_document(pid,c['title'],'official.pdf',1,[{'id':'p1-s1','page':1,'text':'Original source.'}])['id'])
    url=f'/api/projects/{pid}/reference-downloads'
    job=client.post(url,json={'queries':['exact','failure','ambiguous','missing']}).json()
    downloads.run(pid,job['id'])
    result=client.get(url).json()[0]
    assert [i['status'] for i in result['items']]==['imported','failed','needs_selection','not_found']
    assert client.get(f'/api/projects/{other}/reference-downloads').json()==[]
    assert client.post(f'/api/projects/{other}/reference-downloads/{job["id"]}/retry',json={'index':2}).status_code==404
    retry=url+'/'+job['id']+'/retry'
    assert client.post(retry,json={'index':0}).status_code==422
    assert client.post(retry,json={'index':2,'candidate_key':'arxiv:foreign'}).status_code==422
    assert client.post(retry,json={'index':2,'candidate_key':candidate['key']}).status_code==200
    downloads.run(pid,job['id'])
    assert client.get(url).json()[0]['items'][2]['status']=='imported'


def test_pmc_source_validation_and_license(monkeypatch):
    def read(url,maximum=0,params=None):
        if params:return b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><CommonPrefixes><Prefix>PMC100.1/</Prefix></CommonPrefixes></ListBucketResult>'
        if url.endswith('.json'):return json.dumps({'is_pmc_openaccess':'yes','license_code':'CC BY','version':1,'pdf_url':'s3://pmc-oa-opendata/PMC100.1/article.pdf'}).encode()
        return b'%PDF-original'
    original=downloads.s3_read
    with pytest.raises(HTTPException):original('https://127.0.0.1/secrets')
    monkeypatch.setattr(downloads,'s3_read',read)
    content,source=downloads.pmc_pdf('PMC100')
    assert content==b'%PDF-original' and source['license']=='CC BY'
    with pytest.raises(HTTPException):downloads.pmc_pdf('PMC100/../foreign')


def test_ocr_columns_keep_full_width_heading():
    blocks=[{'text':'Title','bbox':[10,0,590,15]}]
    for i in range(8):
        blocks += [{'text':'left'+str(i),'bbox':[20,30+i*12,270,40+i*12]}, {'text':'right'+str(i),'bbox':[330,30+i*12,580,40+i*12]}]
    ordered,columns=order_ocr(blocks,600)
    assert columns and [b['text'] for b in ordered]==['Title']+['left'+str(i) for i in range(8)]+['right'+str(i) for i in range(8)]


def test_graph_matches_true_reference_as_candidate_without_changing_review(client):
    pid,other=create(client),create(client)
    title='Exact target study of random seeds'
    target=core.add_document(pid,title,'target.txt',1,[{'id':'p1-s1','page':1,'text':'Actual paper text.'}])
    source=core.add_document(pid,'The citing study','citing.txt',2,[{'id':'p1-s1','page':1,'text':'We cite the study [1].'}, {'id':'p2-s1','page':2,'kind':'heading','text':'References'}, {'id':'p2-s2','page':2,'text':'[1] Author. '+title+'. Journal, 2024.'}])
    response=client.post(f'/api/projects/{pid}/reference-network/match')
    assert response.status_code==200 and response.json()['created']==1
    data=client.get(f'/api/projects/{pid}/graph-insights').json()
    assert not data['edges'] and data['candidate_edges']==[{'source':source['id'],'target':target['id']}]
    row=client.get(f'/api/projects/{pid}/reference-network').json()['references'][0]
    assert row['status']=='candidate' and title in row['quote'] and row['url']==''
    client.put(f'/api/projects/{pid}/references/'+row['id'],json={'label':'Reviewed label','status':'confirmed','target_document_id':target['id']})
    assert client.post(f'/api/projects/{pid}/reference-network/match').json()['created']==0
    kept=client.get(f'/api/projects/{pid}/reference-network').json()['references'][0]
    assert kept['label']=='Reviewed label' and kept['status']=='confirmed'
    assert not client.post(f'/api/projects/{other}/reference-network/match').json()['created']


def test_title_prefers_real_large_type_over_license_and_author_year_match(client):
    from backend import documents
    pid=create(client)
    doc=core.add_document(pid,'upload-name','paper.txt',2,[
        {'id':'p1-s1','page':1,'kind':'heading','font_size':12,'text':'Provided proper attribution permission is granted.'},
        {'id':'p1-s2','page':1,'kind':'heading','font_size':18,'text':'Attention Is All You Need'},
        {'id':'p1-s3','page':1,'kind':'paragraph','font_size':10,'text':'Actual study body.'}])
    assert documents.profile_for(doc,{})['title']=='Attention Is All You Need'
    core.add_document(pid,'Target study of neural scaling laws','target.txt',1,[{'id':'p1-s1','page':1,'text':'Original study body.'}])
    core.add_document(pid,'Author year citing study','citing.txt',2,[
        {'id':'p1-s1','page':1,'text':'We cite Author (2024).'},
        {'id':'p2-s1','page':2,'kind':'heading','text':'References'},
        {'id':'p2-s2','page':2,'text':'Author, A. Target study of neural scaling laws. Journal (2024).'}])
    result=client.post(f'/api/projects/{pid}/reference-network/match').json()
    assert result['created']==1
