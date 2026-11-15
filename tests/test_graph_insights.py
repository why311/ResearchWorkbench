import math

from backend import app as core
from backend.graph_insights import topology
from tests.test_workbench import client, create


def test_pagerank_direction_dedup_candidates_components():
    documents = [{'id': key, 'title': key} for key in 'abcd']
    references = [{'document_id': a, 'target_document_id': b, 'status': status}
                  for a, b, status in [('b', 'a', 'confirmed'), ('c', 'a', 'confirmed'),
                                       ('c', 'b', 'confirmed'), ('b', 'a', 'confirmed'),
                                       ('a', 'd', 'candidate'), ('d', None, 'confirmed'),
                                       ('a', 'a', 'confirmed')]]
    data = topology(documents, references)
    nodes = {n['id']: n for n in data['nodes']}
    assert nodes['a']['incoming'] == 2 and nodes['a']['outgoing'] == 0
    assert nodes['a']['pagerank'] > nodes['b']['pagerank'] > nodes['c']['pagerank']
    assert nodes['d']['isolated'] and len(data['edges']) == 3
    assert math.isclose(sum(n['pagerank'] for n in nodes.values()), 1, abs_tol=1e-9)
    assert data['components'] == [['a', 'b', 'c'], ['d']]
    assert topology([], []) == {'nodes': [], 'edges': [], 'components': []}


def test_graph_does_not_treat_first_page_citation_as_document_identity(client):
    pid = create(client)
    cited = core.add_document(pid, 'Layer Normalization', '1607.06450v1.pdf', 1, [
        {'id': 'p1-s1', 'page': 1, 'text': 'We build on Deep Speech 2; see arXiv:1512.02595.'}])
    core.add_document(pid, 'Attention Is All You Need', '1706.03762v7.pdf', 1, [
        {'id': 'p1-s1', 'page': 1, 'text': 'For layer normalization see arXiv:1607.06450.'}])
    source = core.add_document(pid, 'Citing paper', 'citing.txt', 2, [
        {'id': 'p1-s1', 'page': 1, 'text': 'These are prior works [1, 2].'},
        {'id': 'p2-s1', 'page': 2, 'text': 'References'},
        {'id': 'p2-s2', 'page': 2, 'text': '[1] Ba et al. Layer Normalization. arXiv:1607.06450, 2016.\n[2] Amodei et al. Deep Speech 2. arXiv:1512.02595, 2015.'}])
    base = f'/api/projects/{pid}'
    assert client.post(base + '/reference-network/match').json()['created'] == 1
    assert client.get(base + '/graph-insights').json()['candidate_edges'] == [
        {'source': source['id'], 'target': cited['id']}]


def test_graph_selects_latest_arxiv_version_and_stops_before_subject_index(client):
    pid = create(client)
    spans = [{'id': 'p1-s1', 'page': 1, 'text': 'Original research paper.'}]
    for filename in ('1706.03762v1.pdf', '1706.03762v7_img.pdf'):
        core.add_document(pid, 'Attention Is All You Need', filename, 1, spans)
    latest = core.add_document(pid, 'Attention Is All You Need', '1706.03762v7.pdf', 1, spans)
    core.add_document(pid, 'Layer Normalization', '1607.06450v1.pdf', 1, spans)
    source = core.add_document(pid, 'Textbook', 'book.pdf', 2, [
        {'id': 'p1-s1', 'page': 1, 'text': 'References\nVaswani et al. Attention is all you need. 2017.'},
        {'id': 'p2-s1', 'page': 2, 'text': 'Index\nLayer normalization, 203'}])
    base = f'/api/projects/{pid}'
    assert client.post(base + '/reference-network/match').json()['created'] == 1
    assert client.post(base + '/reference-network/match').json()['created'] == 0
    assert client.get(base + '/graph-insights').json()['candidate_edges'] == [
        {'source': source['id'], 'target': latest['id']}]


def test_graph_future_sources_and_outline_use_real_passages(client):
    pid, other = create(client), create(client)
    doc = core.add_document(pid, 'Source " ] --> injected', 'source.txt', 2, [
        {'id': 'p1-s1', 'page': 1, 'text': 'Abstract: We study a synthetic validation task.'},
        {'id': 'p2-s1', 'page': 2, 'text': 'Future work: evaluate on a genuinely held-out dataset.'},
        {'id': 'p2-s2', 'page': 2, 'text': 'References: unrelated bibliography.'}])
    second = core.add_document(pid, 'Second source', 'second.txt', 1, [
        {'id': 'p1-s1', 'page': 1, 'text': 'Independent first paragraph without an abstract.'}])
    foreign = core.add_document(other, 'Foreign', 'foreign.txt', 1, [{'id': 'p1-s1', 'page': 1, 'text': 'Secret foreign content.'}])
    base = f'/api/projects/{pid}'
    assert client.get(base + '/graph-insights').json()['nodes'][0]['pagerank'] == .5
    script = client.get(base + '/graph-insights/mermaid').text
    assert 'flowchart LR' in script and '" ] --> injected' not in script
    future = client.get(base + '/future-work').json()['items']
    assert len(future) == 1 and future[0]['id'] == 'p2-s1' and future[0]['page'] == 2
    assert client.get(f'/api/projects/{other}/future-work').json()['items'] == []
    body = {'idea': 'Can this task generalize? {{made_up}} [[cite:unknown]]', 'document_ids': [doc['id'], second['id']]}
    report = client.post(base + '/literature-outline', json=body).json()
    assert report['id'] and len(report['citations']) == 2 and not report['errors']
    assert 'Abstract' in report['template'] and 'Related Work' in report['template']
    assert report['citations'][0]['span_id'] == 'p1-s1'
    path = base + '/reports/' + report['id']
    assert client.post(path + '/generate').status_code == 200
    text = client.get(path + '/artifacts/report.md').text
    assert 'We study a synthetic validation task.' in text and '[1]' in text
    assert client.post(base + '/literature-outline', json={**body, 'document_ids': [foreign['id']]}).status_code == 404
    assert client.post(base + '/literature-outline', json={**body, 'document_ids': [doc['id'], doc['id']]}).status_code == 422
    assert client.post(base + '/literature-outline', json={**body, 'idea': '  '}).status_code == 422


def test_future_heading_followups_stop_at_next_heading(client):
    pid = create(client)
    doc = core.add_document(pid, 'Structured', 'structured.pdf', 1, [])
    with core.db() as conn:
        for ordinal, (kind, text) in enumerate([('heading', 'Future Work'), ('text', 'A specific next experiment.'), ('heading', 'References'), ('text', 'Unrelated bibliography entry.')]):
            conn.execute('INSERT INTO document_blocks VALUES (?,?,?,?,?,?,?,?)', (doc['id'], f'p1-s{ordinal}', 1, ordinal, kind, text, '[]', '{}'))
    items = client.get(f'/api/projects/{pid}/future-work').json()['items']
    assert [s['text'] for s in items] == ['Future Work', 'A specific next experiment.']


def test_outline_cites_abstract_content_instead_of_heading(client):
    pid = create(client)
    doc = core.add_document(pid, 'Structured abstract', 'structured.pdf', 1, [])
    with core.db() as conn:
        for ordinal, (kind, text) in enumerate([('heading', 'Paper title'), ('heading', 'Abstract'), ('text', 'Actual abstract describing the task.'), ('heading', 'Introduction')]):
            conn.execute('INSERT INTO document_blocks VALUES (?,?,?,?,?,?,?,?)', (doc['id'], f'p1-s{ordinal}', 1, ordinal, kind, text, '[]', '{}'))
    response = client.post(f'/api/projects/{pid}/literature-outline', json={'idea': 'A validation plan', 'document_ids': [doc['id']]})
    assert response.status_code == 200
    assert response.json()['citations'][0]['span_id'] == 'p1-s2'
