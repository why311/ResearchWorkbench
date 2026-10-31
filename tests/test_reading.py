from backend import app as core
from tests.test_documents import client, project


def test_manual_reading_sources_updates_and_export(client):
    pid=project(client)
    did=client.post(f'/api/projects/{pid}/documents',files={'file':('study.txt',b'The actual reported score is 0.8.\n\nThe limitation is external validation.')} ).json()['id']
    url=f'/api/projects/{pid}/documents/{did}/reading'
    entry={'section':'experiments','title':'Reported score','body':'Author interpretation','grade':'stated','span_id':'p1-s1'}
    assert client.post(url,json={**entry,'span_id':''}).status_code==422
    assert client.post(url,json={**entry,'span_id':'p99-s1'}).status_code==422
    result=client.post(url,json=entry).json();assert result[0]['source']['text']=='The actual reported score is 0.8.'
    eid=result[0]['id']
    assert client.put(url+'/'+eid,json={**entry,'body':'Revised explanation'}).json()[0]['id']==eid
    assert len(client.get(url).json())==1
    exported=client.get(url+'.md').text
    assert 'Revised explanation' in exported and '0.8' in exported and 'p1-s1' in exported
    other=project(client)
    assert client.get(f'/api/projects/{other}/documents/{did}/reading').status_code==404
    second=client.post(f'/api/projects/{other}/documents',files={'file':('second.txt',b'Other source.')} ).json()['id']
    assert client.put(f'/api/projects/{other}/documents/{second}/reading/'+eid,json={**entry,'grade':'inferred','span_id':''}).status_code==404


def test_reading_limit_does_not_block_existing_note_edit(client):
    pid=project(client);did=client.post(f'/api/projects/{pid}/documents',files={'file':('study.txt',b'Original source.')} ).json()['id']
    url=f'/api/projects/{pid}/documents/{did}/reading';entry={'section':'limits','title':'Pending check','body':'No conclusion','grade':'unreported'}
    for _ in range(40):assert client.post(url,json=entry).status_code==200
    assert client.post(url,json=entry).status_code==422
    eid=client.get(url).json()[0]['id']
    assert client.put(url+'/'+eid,json={**entry,'title':'Updated check'}).status_code==200
    assert client.post(url,json={**entry,'title':'   '}).status_code==422
