import io
import json
import zipfile
from backend import translations
from tests.test_documents import client, project


def setup(client, text='The score is 0.8.\n\n<script>alert(1)</script>'):
    pid=project(client)
    did=client.post(f'/api/projects/{pid}/documents',files={'file':('source.md',text.encode())}).json()['id']
    return pid, f'/api/projects/{pid}/documents/{did}'


def test_save_export_and_project_ownership(client):
    pid,base=setup(client)
    assert client.put(base+'/translations/p1-s1',json={'text':'得分为0.8。','reviewed':True}).status_code==200
    rows=client.get(base+'/translations').json()['items']
    assert rows[0]['text']=='The score is 0.8.' and rows[0]['translation']['reviewed']==1
    assert client.put(base+'/translations/missing',json={'text':'无来源'}).status_code==404
    assert client.put(base+'/translations/p1-s1',json={'text':'  '}).status_code==422
    assert client.get(base+'/translations?page=2').status_code==422
    other=base.replace(pid,project(client))
    assert client.get(other+'/translations').status_code==404
    assert client.put(other+'/translations/p1-s1',json={'text':'越界'}).status_code==404
    assert client.get(other+'/translations-export').status_code==404
    client.put(base+'/translations/p1-s2',json={'text':'<script>alert(2)</script>'})
    bundle=zipfile.ZipFile(io.BytesIO(client.get(base+'/translations-export').content))
    assert '<script>' not in bundle.read('bilingual.html').decode()
    records=json.loads(bundle.read('sources.json'))['translations']
    assert records[0]['source']['text']=='The score is 0.8.'
    assert records[0]['reviewed']==1 and records[1]['source']['page']==1


def test_model_correspondence_and_concurrent_manual_edit(client,monkeypatch):
    _,base=setup(client)
    def model(*args):
        client.put(base+'/translations/p1-s1',json={'text':'人工优先','reviewed':True})
        return {'translations':[{'span_id':'p1-s1','source':'The score is 0.8.','translation':'模型译文'},
            {'span_id':'p1-s2','source':'<script>alert(1)</script>','translation':'第二段译文'},
            {'span_id':'unknown','source':'other','translation':'不应保存'}]}
    monkeypatch.setattr(translations,'model_json',model)
    result=client.post(base+'/translate',json={'page':1}).json()
    assert result['items'][0]['translation']['text']=='人工优先'
    assert result['items'][0]['translation']['reviewed']==1
    assert result['items'][1]['translation']['method']=='model'
    assert client.post(base+'/translate',json={'page':1}).status_code==409


def test_failed_generation_and_late_page_segments(client,monkeypatch):
    _,base=setup(client)
    monkeypatch.setattr(translations,'model_json',lambda *a:None)
    assert client.post(base+'/translate',json={'page':1}).status_code==409
    monkeypatch.setattr(translations,'model_json',lambda *a:{'translations':[{'span_id':'p1-s1','source':'wrong source','translation':'错误对应'}]})
    assert client.post(base+'/translate',json={'page':1}).status_code==502
    assert all(s['translation'] is None for s in client.get(base+'/translations').json()['items'])
    _,long_base=setup(client,'\n\n'.join(f'Paragraph {i}' for i in range(105)))
    last=client.get(long_base+'/translations?offset=80').json()
    assert len(last['items'])==25 and not last['has_more']
    assert last['items'][-1]['id']=='p1-s105'
