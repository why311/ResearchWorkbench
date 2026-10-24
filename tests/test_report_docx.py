import io
import json
import zipfile

from docx import Document
from lxml import etree

from backend import app as core
from tests.test_workbench import client, create


def completed_run(pid, value):
    rid = core.uid()
    with core.db() as conn:
        conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)', (rid, pid, '真实结果来源（导出测试记录）', 'succeeded', json.dumps({'recipe': 'analysis', 'seed': 42}), json.dumps({'score': value}), '', '[]', core.now(), core.now()))
    return rid


def word_text(content):
    doc = Document(io.BytesIO(content))
    return '\n'.join(p.text for p in doc.paragraphs) + '\n' + '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)


def test_word_uses_generated_version_and_has_native_content(client):
    pid, other = create(client), create(client)
    a, b = completed_run(pid, 1.25), completed_run(pid, 2.5)
    body = {'title': '中文成果导出', 'template': '## 研究结果\n\n平均值为 **{{score}}**，公式 $\\bar{x}=\\frac{a}{b}\\sum_{i=1}^{n}x_i$。\n\n- 核对来源\n- 记录局限\n\n| 项目 | 值 |\n|---|---|\n| 均值 | {{score}} |\n\n![外部图](file:///does-not-exist.png)\n\n```python\nprint("not executed")\n```',
        'bindings': [{'alias': 'score', 'run_id': a, 'metric': 'score', 'precision': 2}], 'chart_run_ids': [a, b], 'chart_metrics': ['score']}
    report = client.post(f'/api/projects/{pid}/reports', json=body).json()
    base = f'/api/projects/{pid}/reports/{report["id"]}'
    assert client.get(base + '/word').status_code == 409
    assert client.get(f'/api/projects/{other}/reports/{report["id"]}/word').status_code == 404
    client.post(base + '/generate')
    first = client.get(base + '/word')
    assert first.status_code == 200, first.text if first.status_code != 200 else ''
    assert first.headers['content-type'].startswith('application/vnd.openxmlformats')
    assert 'v1.docx' in first.headers['content-disposition']
    text = word_text(first.content)
    assert '平均值为 1.25' in text and 'not executed' in text and '实际配置' in text
    archive = zipfile.ZipFile(io.BytesIO(first.content))
    xml = archive.read('word/document.xml')
    root = etree.fromstring(xml)
    namespaces = {'m': 'http://schemas.openxmlformats.org/officeDocument/2006/math', 'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    assert root.xpath('count(//m:f)', namespaces=namespaces) == 1
    assert root.xpath('count(//m:bar/m:barPr/m:pos)', namespaces=namespaces) == 1
    assert root.xpath('count(//m:nary)', namespaces=namespaces) == 1
    assert root.xpath('count(//w:tblHeader)', namespaces=namespaces) >= 2
    assert any(n.startswith('word/media/') for n in archive.namelist())
    assert b'TargetMode="External"' not in archive.read('word/_rels/document.xml.rels')
    body['title'] = '后来修改的草稿标题'
    body['bindings'][0]['run_id'] = b
    body['template'] = '后来草稿中的均值 {{score}}。'
    client.put(base, json=body)
    old = word_text(client.get(base + '/word').content)
    assert '中文成果导出' in old and '平均值为 1.25' in old and '后来修改' not in old
    client.post(base + '/generate')
    new = client.get(base + '/word')
    assert 'v2.docx' in new.headers['content-disposition']
    assert '后来草稿中的均值 2.50' in word_text(new.content)


def test_bad_math_does_not_break_existing_markdown_export(client):
    pid = create(client)
    report = client.post(f'/api/projects/{pid}/reports', json={'title': '公式错误', 'template': r'数学公式 $\frac{a}{$'}).json()
    base = f'/api/projects/{pid}/reports/{report["id"]}'
    assert client.post(base + '/generate').status_code == 200
    assert client.get(base + '/word').status_code == 422
    assert client.get(base + '/export').status_code == 200
    assert client.get(base + '/artifacts/report.md').status_code == 200
