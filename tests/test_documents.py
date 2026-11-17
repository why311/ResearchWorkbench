import io
import time

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import app as core
from backend import documents
from tests.test_workbench import client, create


def pdf_bytes(pages=1, version=7, seed=42, table=False):
    writer = PdfWriter()
    writer.add_metadata({'/Title': 'Synthetic parsing fixture'})
    for number in range(1, pages + 1):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        data = f'BT /F1 20 Tf 50 740 Td (1 Experimental Settings) Tj /F1 12 Tf 0 -40 Td (Synthetic arXiv:9999.12345v{version} fixture only.) Tj 0 -25 Td (Training uses random seed {seed} and an NVIDIA V100 GPU.) Tj 0 -25 Td (We report test accuracy. UniquePage{number}.) Tj ET'
        if table:
            data += ' 50 500 m 400 500 l S 50 470 m 400 470 l S 50 440 m 400 440 l S 50 440 m 50 500 l S 225 440 m 225 500 l S 400 440 m 400 500 l S BT /F1 12 Tf 60 480 Td (Metric) Tj 175 0 Td (Value) Tj -175 -30 Td (Accuracy) Tj 175 0 Td (0.75) Tj ET'
        stream = DecodedStreamObject(); stream.set_data(data.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    output = io.BytesIO(); writer.write(output)
    return output.getvalue()


def wait(client, pid, jid, seconds=90):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        job = client.get(f'/api/projects/{pid}/document-ingestions/{jid}').json()
        if job['status'] not in {'queued', 'running'}:
            assert job['status'] == 'completed', job
            return job
        time.sleep(.15)
    raise AssertionError('PDF ingestion did not finish')


def ingest(client, pid, content, filename='fixture.pdf'):
    response = client.post(f'/api/projects/{pid}/document-ingestions', files={'file': (filename, content)})
    assert response.status_code == 200, response.text
    return wait(client, pid, response.json()['id'])


def test_long_document_paging_structure_and_grounded_search(client):
    pid = create(client)
    job = ingest(client, pid, pdf_bytes(541))
    assert job['completed'] == 541 and job['profile']['characters'] > 10000
    doc = client.get(f'/api/projects/{pid}').json()['documents'][0]
    assert doc['pages'] == 541 and len(doc['spans']) <= 80 and doc['span_count'] > 541
    assert doc['ingestion']['profile']['headings']
    did = doc['id']
    last = client.get(f'/api/projects/{pid}/documents/{did}/spans?page=541').json()
    assert all(s['page'] == 541 for s in last['items']) and last['details']['width'] == 612
    assert any('UniquePage541' in s['text'] for s in last['items'])
    assert all(len(s['bbox']) == 4 for s in last['items'])
    hit = client.post(f'/api/projects/{pid}/evidence', json={'question': 'UniquePage541'}).json()['evidence']
    assert any(e['page'] == 541 for e in hit)
    original = client.get(f'/api/projects/{pid}/documents/{did}/original')
    assert original.content.startswith(b'%PDF')
    image = client.get(f'/api/projects/{pid}/documents/{did}/page-image/541')
    assert image.status_code == 200 and image.content.startswith(b'\x89PNG')
    other = create(client)
    assert client.get(f'/api/projects/{other}/documents/{did}/spans').status_code == 404
    assert client.get(f'/api/projects/{other}/documents/{did}/page-image/1').status_code == 404
    assert client.get(f'/api/projects/{pid}/documents/{did}/spans?page=542').status_code == 422
    later = last['items'][-1]
    note = client.post(f'/api/projects/{pid}/research-notes', json={'title': 'Later-page evidence', 'source_refs': [{'document_id': did, 'span_id': later['id']}]}).json()
    assert note['sources'][0]['page'] == 541
    anchored = client.get(f'/api/projects/{pid}/documents/{did}/spans?anchor={later["id"]}&limit=1').json()
    assert anchored['items'][0]['id'] == later['id'] and anchored['offset'] > 0


def test_content_versions_keep_originals_and_tables(client):
    pid = create(client)
    newer = ingest(client, pid, pdf_bytes(version=7, table=True), 'paper.pdf')
    older = ingest(client, pid, pdf_bytes(version=1, table=True), 'different-name.pdf')
    assert newer['document_id'] != older['document_id']
    candidate = older['profile']['duplicates'][0]
    assert candidate['document_id'] == newer['document_id'] and candidate['same_identifier']
    assert '库中版本更新' in candidate['suggestion']
    assert older['profile']['version'] == 1 and older['profile']['arxiv'] == '9999.12345'
    page = client.get(f'/api/projects/{pid}/documents/{newer["document_id"]}/spans').json()
    assert page['details']['tables'] and 'Accuracy' in str(page['details']['tables'])
    assert len(client.get(f'/api/projects/{pid}').json()['documents']) == 2


def test_scan_ocr_is_really_executed(client):
    pid = create(client)
    image = Image.new('RGB', (1200, 700), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 42)
    draw.text((70, 100), 'Experimental Settings', fill='black', font=font)
    draw.text((70, 200), 'Random seed 42', fill='black', font=font)
    draw.text((70, 300), 'GPU NVIDIA V100', fill='black', font=font)
    memory = io.BytesIO(); image.save(memory, format='PDF'); image.close()
    job = ingest(client, pid, memory.getvalue(), 'image-only.pdf')
    page = client.get(f'/api/projects/{pid}/documents/{job["document_id"]}/spans').json()
    assert page['details']['method'] == 'ocr'
    assert 'seed 42' in ' '.join(s['text'] for s in page['items'])
    assert all('confidence' in s for s in page['items'])


def test_cancel_resume_and_bad_inputs(client, monkeypatch):
    pid = create(client)
    monkeypatch.setattr(documents.POOL, 'submit', lambda *_: None)
    response = client.post(f'/api/projects/{pid}/document-ingestions', files={'file': ('valid.pdf', pdf_bytes())})
    record = response.json()
    jid = record['id']
    assert client.post(f'/api/projects/{pid}/document-ingestions/{jid}/cancel').json()['status'] == 'cancelled'
    assert client.post(f'/api/projects/{pid}/document-ingestions/{jid}/resume').json()['status'] == 'queued'
    other = create(client)
    assert client.post(f'/api/projects/{other}/document-ingestions/{jid}/cancel').status_code == 404
    assert client.post(f'/api/projects/{pid}/document-ingestions', files={'file': ('broken.pdf', b'broken')}).status_code == 422
    assert client.post(f'/api/projects/{pid}/document-ingestions', files={'file': ('wrong.txt', b'text')}).status_code == 422
    # The old synchronous route keeps its existing 300-page protection.
    assert client.post(f'/api/projects/{pid}/documents', files={'file': ('too-long.pdf', pdf_bytes(301))}).status_code == 422
