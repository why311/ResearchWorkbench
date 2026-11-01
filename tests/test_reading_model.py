import httpx
from backend import reading, model
from tests.test_documents import client, project


def setup(client):
    pid=project(client)
    did=client.post(f'/api/projects/{pid}/documents',files={'file':('paper.txt',b'Reported score is 0.8.')} ).json()['id']
    return f'/api/projects/{pid}/documents/{did}/reading'


def test_generated_notes_validate_sources_and_preserve_manual(client,monkeypatch):
    url=setup(client)
    client.post(url,json={'section':'limits','title':'Manual','body':'Keep me','grade':'inferred'})
    entry={'section':'experiments','title':'Score','body':'Model interpretation','grade':'stated','span_id':'p1-s1','quote':'score is 0.8'}
    monkeypatch.setattr(reading,'model_json',lambda *a:{'entries':[entry,{**entry,'quote':'score is 1.0'},{**entry,'span_id':'other-paper'},None]})
    result=client.post(url+'/generate',json={'page':1}).json()
    assert result['added']==1 and result['rejected']==3
    assert result['entries'][0]['body']=='Keep me' and len(result['entries'])==2
    other=project(client)
    assert client.post(url.replace(url.split('/')[3],other)+'/generate',json={'page':1}).status_code==404
    assert client.post(url+'/generate',json={'page':2}).status_code==422


def test_generation_failure_and_capacity_are_atomic(client,monkeypatch):
    url=setup(client)
    monkeypatch.setattr(reading,'model_json',lambda *a:None)
    assert client.post(url+'/generate',json={'page':1}).status_code==409
    monkeypatch.setattr(reading,'model_json',lambda *a:{'entries':[{'section':'limits','title':'Invalid','grade':'stated'}]})
    assert client.post(url+'/generate',json={'page':1}).status_code==502
    assert client.get(url).json()==[]
    entry={'section':'limits','title':'Manual','grade':'unreported'}
    for _ in range(39):client.post(url,json=entry)
    def concurrent(*args):
        client.post(url,json=entry)
        return {'entries':[entry]}
    monkeypatch.setattr(reading,'model_json',concurrent)
    assert client.post(url+'/generate',json={'page':1}).status_code==409
    assert len(client.get(url).json())==40
    assert client.post(url+'/generate',json={'page':1}).status_code==422


def test_provider_request_and_invalid_output(monkeypatch):
    monkeypatch.setenv('RESEARCH_MODEL_URL','http://127.0.0.1:9999/v1')
    monkeypatch.setenv('RESEARCH_MODEL_NAME','test-model')
    monkeypatch.setenv('RESEARCH_MODEL_KEY','test-key')
    def post(url,**kw):
        assert url.endswith('/v1/chat/completions') and kw['trust_env'] is False
        assert kw['headers']['Authorization']=='Bearer test-key'
        assert len(kw['json']['messages'])==2
        return httpx.Response(200,json={'choices':[{'message':{'content':'```json\n{"entries":[]}\n```'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(model.httpx,'post',post)
    assert model.model_json('instruction','material')=={'entries':[]}
