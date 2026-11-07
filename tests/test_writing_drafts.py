import json

from backend import app as core
from tests.test_documents import client, project


def test_outline_uses_abstract_body_and_exports_after_edit(client):
    pid = project(client)
    base = f'/api/projects/{pid}'
    text = 'Abstract\n\nTraining records random seed 42.\n\nFuture work will assess larger datasets.'
    doc = client.post(base + '/documents', files={'file': ('paper.md', text.encode())}).json()
    response = client.post(base + '/literature-outline', json={'idea': '核对训练设置', 'document_ids': [doc['id']]})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['citations'][0]['span_id'] == 'p1-s2'
    path = base + '/writing-drafts/' + draft['id']
    edit = {'title': '修改后的开题', 'template': '对照训练设置 [[cite:paper1]]'}
    assert client.put(path, json=edit).status_code == 200
    exported = client.get(path + '/export')
    assert '对照训练设置 [1]' in exported.text and 'Training records random seed 42.' in exported.text
    other = f'/api/projects/{project(client)}/writing-drafts/{draft["id"]}'
    assert client.get(other + '/export').status_code == 404
    assert client.put(other, json=edit).status_code == 404
    assert client.get(base + '/future-work').json()['items'][0]['id'] == 'p1-s3'


def test_review_rejects_unverifiable_quotes_before_persisting(client, monkeypatch):
    pid = project(client)
    base = f'/api/projects/{pid}'
    quote = 'Training uses random seed 42.'
    did = client.post(base + '/documents', files={'file': ('paper.txt', quote.encode())}).json()['id']

    def respond(_, material):
        candidate = json.loads(material)[0]
        return {'claims': [
            {'section': 'method', 'text': '种子是42。', 'citation': candidate['citation'], 'quote': quote},
            {'section': 'method', 'text': '捏造的GPU结果', 'citation': candidate['citation'], 'quote': '100 GPUs'},
        ]}

    monkeypatch.setattr(core, 'model_json', respond)
    response = client.post(base + '/literature-review', json={'question': 'random seed', 'document_ids': [did]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['rejected'] == 1 and len(result['claims']) == 1
    exported = client.get(base + f"/writing-drafts/{result['report']['id']}/export").text
    assert '种子是42。' in exported and quote in exported and '捏造的GPU结果' not in exported
