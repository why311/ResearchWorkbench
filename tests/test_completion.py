import io
import json
from concurrent.futures import Future

from docx import Document
from docx.shared import Cm, Pt
from fastapi.responses import Response

from backend import app as core, literature, research_completion as completion
from backend.analysis_runner import analyze
from tests.test_workbench import client, create


def add(pid, title='Source', text='Abstract: The measured accuracy is 0.8.'):
    return core.add_document(pid, title, title+'.txt', 2, [
        {'id':'p1-s1','page':1,'text':text}, {'id':'p2-s1','page':2,'text':'The method has not been tested on external datasets.'}])


def test_versions_compare_and_keep_historical_evidence(client):
    pid, other = create(client), create(client)
    old, new, foreign = add(pid,'v1'), add(pid,'v7','Abstract: The measured accuracy is 0.9.'), add(other,'Foreign')
    base=f'/api/projects/{pid}'
    report=client.post(base+'/reports',json={'title':'Historical','template':'Result [[cite:a]]','citations':[{'alias':'a','document_id':old['id'],'span_id':'p1-s1'}]}).json()
    assert client.post(base+'/reports/'+report['id']+'/generate').status_code==200
    choice={'previous_id':old['id'],'current_id':new['id'],'mode':'prefer'}
    assert client.post(base+'/document-versions',json=choice).status_code==200
    assert client.post(base+'/document-versions',json={**choice,'previous_id':new['id'],'current_id':old['id']}).status_code==409
    data=client.get(base+'/document-diff',params={'previous_id':old['id'],'current_id':new['id']}).json()
    assert data['total']==1 and data['items'][0]['before'][0]['text'].endswith('0.8.')
    assert data['items'][0]['after'][0]['text'].endswith('0.9.')
    assert '0.8' in client.get(base+'/reports/'+report['id']+'/artifacts/report.md').text
    assert client.get(base+'/document-diff',params={'previous_id':old['id'],'current_id':foreign['id']}).status_code==404
    assert client.get(base+'/document-diff/export',params={'previous_id':old['id'],'current_id':new['id']}).json()['total']==1


def test_numbered_references_ranges_and_multiple_entries(client):
    pid=create(client)
    doc=core.add_document(pid,'Numbered','numbered.txt',5,[
        {'id':'p1-s1','page':1,'text':'Related studies [1, 2] and a range [2-3]. Unknown [99].'},
        {'id':'p3-s0','page':3,'text':'Table row\n[2] Prior method 0.8'},
        {'id':'p3-s1','page':3,'text':'References','kind':'heading'},
        {'id':'p3-s2','page':3,'text':'[1] Author A. First paper.\n[2] Author B. Second paper.'},
        {'id':'p4-s1','page':4,'text':'[3] Author C. Third paper.'},
        {'id':'p5-s1','page':5,'text':'A diagram page with unrelated text and no numbered entries.'},
        {'id':'p5-s2','page':5,'kind':'heading','text':'Appendix'},
        {'id':'p5-s3','page':5,'text':'[4] This is an appendix list, not a bibliography entry.'}])
    data=client.get(f'/api/projects/{pid}/documents/{doc["id"]}/citation-map').json()
    assert [r['number'] for r in data['references']]==[1,2,3]
    assert [len(r['backlinks']) for r in data['references']]==[1,3,1]
    assert data['references'][1]['text'].startswith('[2]')
    assert 'unrelated' not in data['references'][-1]['text']
    assert data['unmatched'][0]['number']==99


def test_translation_selection_and_resume_preserve_manual_text(client,monkeypatch):
    pid=create(client); doc=add(pid)
    base=f'/api/projects/{pid}/documents/{doc["id"]}'
    monkeypatch.setattr(core,'model_json',lambda *args,**kwargs:{'translation':'准确率'})
    assert client.post(base+'/translate-selection',json={'span_id':'p1-s1','selection':'accuracy'}).json()['translation']=='准确率'
    assert client.post(base+'/translate-selection',json={'span_id':'p1-s1','selection':'invented source'}).status_code==422
    assert client.put(base+'/translations/p1-s1',json={'text':'人工译文','reviewed':True}).status_code==200
    monkeypatch.setattr(core,'settings',lambda:{'base_url':'http://fixture','model':'fixture','api_key':''})
    pending = Future()
    monkeypatch.setattr(literature.TRANSLATION_POOL,'submit',lambda *_:pending)
    def model(_instruction,material):
        return {'translations':[{'span_id':r['span_id'],'source':r['source'],'translation':'模型译文'} for r in json.loads(material)]}
    monkeypatch.setattr(core,'model_json',model)
    body={'start_page':1,'end_page':2,'language':'zh'}
    assert client.post(base+'/translation-job',json=body).status_code==200
    assert client.post(base+'/translation-job',json=body).status_code==409
    literature.run_translation(pid,doc['id'],literature.FullTranslateBody(**body))
    pending.set_result(None)
    assert client.get(base+'/translation-job').json()['status']=='completed'
    assert client.get(base+'/translations').json()['items'][0]['translation']['text']=='人工译文'
    assert client.get(base+'/translations?page=2').json()['items'][0]['translation']['text']=='模型译文'


def test_translation_cannot_resume_until_cancelled_request_finishes(client,monkeypatch):
    pid=create(client); doc=add(pid)
    base=f'/api/projects/{pid}/documents/{doc["id"]}/translation-job'
    monkeypatch.setattr(core,'settings',lambda:{'base_url':'http://fixture','model':'fixture','api_key':''})
    pending=Future()
    monkeypatch.setattr(literature.TRANSLATION_POOL,'submit',lambda *_:pending)
    body={'start_page':1,'end_page':2}
    assert client.post(base,json=body).status_code==200
    assert client.delete(base).json()['status']=='cancelled'
    assert client.post(base,json=body).status_code==409
    assert client.get(base).json()['status']=='cancelled'
    pending.set_result(None)
    replacement=Future()
    monkeypatch.setattr(literature.TRANSLATION_POOL,'submit',lambda *_:replacement)
    assert client.post(base,json=body).status_code==200
    assert client.get(base).json()['status']=='queued'
    replacement.set_result(None)


def test_review_rejects_untraceable_claims_and_timeline_dates(client,monkeypatch):
    pid,foreign=create(client),create(client); doc=add(pid); secret=add(foreign)
    base=f'/api/projects/{pid}'
    def model(_instruction,material):
        rows=json.loads(material); s=rows[0]
        return {'claims':[{'section':'method','text':'A bounded statement.','citation':s['citation'],'quote':s['text']},
                          {'section':'method','text':'Invented.','citation':'foreign:p1','quote':'absent'}], 'gaps':['Need external validation.']}
    monkeypatch.setattr(core,'model_json',model)
    r=client.post(base+'/literature-review',json={'question':'measured accuracy','document_ids':[doc['id']]}).json()
    assert len(r['claims'])==1 and r['rejected']==1 and len(r['report']['citations'])==1
    monkeypatch.setattr(core,'model_json',lambda *_:{'checks':[{'alias':'review1','verdict':'unsupported','reason':'The quote does not establish this claim.'}]})
    check=client.post(base+'/reports/'+r['report']['id']+'/citation-check').json()
    assert not check['stale'] and check['result']['checks'][0]['verdict']=='unsupported'
    changed={**r['report'],'template':r['report']['template']+'\n\nAuthor revision.'}
    assert client.put(base+'/reports/'+r['report']['id'],json=changed).status_code==200
    assert client.get(base+'/reports/'+r['report']['id']+'/citation-check').json()['stale']
    assert client.post(base+'/literature-review',json={'question':'accuracy','document_ids':[secret['id']]}).status_code==404
    event={'question':'External validation','document_id':doc['id'],'span_id':'p2-s1','event_date':'2026-02-30','assessment':'open','note':'Condition not tested.'}
    assert client.post(base+'/research-timeline',json=event).status_code==422
    records=client.post(base+'/research-timeline',json={**event,'event_date':'2026-02'}).json()
    assert records[0]['quote']=='The method has not been tested on external datasets.'
    assert client.delete(f'/api/projects/{foreign}/research-timeline/'+records[0]['id']).status_code==404


def test_diagram_filters_unknown_edges_and_encodes_labels(client,monkeypatch):
    pid=create(client);doc=add(pid)
    monkeypatch.setattr(core,'model_json',lambda *_:{'nodes':[{'id':'n1','label':'Input "] --> malicious','citation':doc['id']+':p1-s1'},{'id':'n2','label':'Test step'}], 'edges':[{'source':'n1','target':'n2'},{'source':'n2','target':'unknown'}]})
    result=client.post(f'/api/projects/{pid}/research-diagram',json={'question':'accuracy','document_ids':[doc['id']]}).json()
    assert len(result['nodes'])==2 and len(result['edges'])==1
    assert '"] --> malicious' not in result['mermaid'] and result['nodes'][1]['status']=='proposed'


def test_page_model_notes_never_replace_original(client,monkeypatch):
    pid=create(client); doc=add(pid)
    monkeypatch.setattr(completion,'page_image',lambda *_:Response(b'PNG fixture',media_type='image/png'))
    monkeypatch.setattr(core,'model_json',lambda *args,**kwargs:{'summary':'Model interpretation','formulas':[{'latex':'x^2','uncertain':True}]})
    base=f'/api/projects/{pid}/documents/{doc["id"]}'
    assert client.post(base+'/interpret-page',json={'page':1}).json()['result']['reviewed'] is False
    assert client.get(base+'/spans').json()['items'][0]['text']=='Abstract: The measured accuracy is 0.8.'


def test_real_charts_and_data_captions(tmp_path):
    data=tmp_path/'data.csv'; data.write_text('group,x,y,z\nA,1,2,3\nA,2,4,6\nB,3,,9\nB,4,8,12\n',encoding='utf-8')
    output=tmp_path/'out'
    result=analyze(data,{'columns':['x','y','z'],'missing':'keep','methods':['summary','line','radar','radar3d'],'group_by':'group','x_column':'x'},output)
    assert result['summary'][1]['count']==3 and result['audit']['output_rows']==4
    for file in ('line.png','radar.png','radar3d.png'):
        assert (output/file).stat().st_size>1000 and file in result['captions']
    assert '缺失' in result['captions']['line.png'] and '非第三项测量值' in result['captions']['radar3d.png']


def test_multiuser_projects_and_settings_are_isolated(client,monkeypatch):
    monkeypatch.setattr(core,'AUTH_USERS',{'alice':'alice-password-long-123','bob':'bob-password-long-456'})
    assert client.get('/api/projects').status_code==401
    client.auth=('alice','alice-password-long-123'); first=create(client); add(first)
    client.auth=('bob','bob-password-long-456'); second=create(client)
    assert [p['id'] for p in client.get('/api/projects').json()]==[second]
    assert client.get('/api/projects/'+first).status_code==404
    assert client.get(f'/api/projects/{first}/document-versions').status_code==404
    assert client.get('/api/settings').status_code==403
    assert client.get('/api/session').json()['username']=='bob'
    client.auth=('bob','wrong'); assert client.get('/').status_code==401
    client.auth=None


def test_school_word_inherits_template_and_generated_version(client):
    pid=create(client); templates=core.DATA/'templates'; templates.mkdir()
    d=Document(); d.sections[0].page_width=Cm(21);d.sections[0].page_height=Cm(29.7); d.styles['Normal'].font.size=Pt(12)
    d.styles.element.remove(d.styles['Title']._element)
    d.styles.element.remove(d.styles['List Bullet']._element)
    d.add_paragraph('Template instruction that must not remain in the paper.')
    path=templates/'school.docx';d.save(path);before=path.read_bytes()
    base=f'/api/projects/{pid}/reports'
    report=client.post(base,json={'title':'研究论文','template':'## 实验方法\n\n真实记录与公式 $x^2$。\n\n- 检查来源'}).json(); rid=report['id']
    assert client.post(base+'/'+rid+'/generate').status_code==200
    result=client.get(base+'/'+rid+'/word?template=school');assert result.status_code==200
    out=Document(io.BytesIO(result.content))
    assert out.sections[0].page_width==Document(io.BytesIO(before)).sections[0].page_width and out.styles['Normal'].font.size.pt==12
    assert 'Template instruction' not in '\n'.join(p.text for p in out.paragraphs)
    assert path.read_bytes()==before


def test_deepseek_configuration_aliases_preserve_only_same_service_key(client):
    assert client.put('/api/settings',json={'base_url':'https://api.deepseek.com/anthropic','model':'v4.1 flash','api_key':'fixture-only-key'}).status_code==200
    saved=client.get('/api/settings').json()
    assert saved['base_url']=='https://api.deepseek.com' and saved['model']=='deepseek-flash' and saved['has_key']
    assert 'fixture-only-key' not in json.dumps(saved)
    client.put('/api/settings',json={'base_url':'https://api.deepseek.com/v1','model':'deepseek-flash','api_key':''})
    assert client.get('/api/settings').json()['has_key']
    client.put('/api/settings',json={'base_url':'https://example.invalid/v1','model':'test','api_key':''})
    assert not client.get('/api/settings').json()['has_key']
