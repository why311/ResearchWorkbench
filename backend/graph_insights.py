"""Local citation topology and source-backed writing preparation; no model claims."""
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app as core
from .ingestion import document, spans
from .references import network

router = APIRouter(prefix='/api')


def topology(documents, references):
    ids = {d['id'] for d in documents}
    # Two identifiers for the same linked paper still represent one citation edge.
    edges = sorted({(r['document_id'], r['target_document_id']) for r in references
                    if r['status'] == 'confirmed' and r['document_id'] in ids
                    and r['target_document_id'] in ids and r['document_id'] != r['target_document_id']})
    incoming, outgoing, neighbors = ({i: set() for i in ids} for _ in range(3))
    for source, target in edges:
        incoming[target].add(source)
        outgoing[source].add(target)
        neighbors[source].add(target)
        neighbors[target].add(source)
    ranks = {i: 1 / len(ids) for i in ids}
    for _ in range(100):
        dangling = sum(ranks[i] for i in ids if not outgoing[i])
        updated = {i: .15 / len(ids) + .85 * (dangling / len(ids)
                   + sum(ranks[j] / len(outgoing[j]) for j in incoming[i])) for i in ids}
        delta = sum(abs(updated[i] - ranks[i]) for i in ids)
        ranks = updated
        if delta < 1e-10:
            break
    components, visited = [], set()
    for node in sorted(ids):
        if node in visited:
            continue
        component, pending = [], [node]
        visited.add(node)
        while pending:
            current = pending.pop()
            component.append(current)
            for neighbor in sorted(neighbors[current] - visited):
                visited.add(neighbor)
                pending.append(neighbor)
        components.append(sorted(component))
    nodes = [{**d, 'incoming': len(incoming[d['id']]), 'outgoing': len(outgoing[d['id']]),
              'pagerank': ranks[d['id']], 'isolated': not neighbors[d['id']]} for d in documents]
    nodes.sort(key=lambda d: (-d['pagerank'], -d['incoming'], d['id']))
    return {'nodes': nodes, 'edges': [{'source': a, 'target': b} for a, b in edges], 'components': components}


@router.get('/projects/{pid}/graph-insights')
def insights(pid: str):
    data = network(pid)
    result = topology(data['documents'], data['references'])
    linked = [r for r in data['references'] if r['status'] == 'confirmed' and r['target_document_id']]
    candidate_edges = sorted({(r['document_id'],r['target_document_id']) for r in data['references'] if r['status']=='candidate' and r['target_document_id'] and r['document_id']!=r['target_document_id']})
    return {**result, 'candidate_edges': [{'source':a,'target':b} for a,b in candidate_edges], 'excluded_references': len(data['references']) - len(linked),
            'summary': f"本项目有{len(result['nodes'])}篇全文、{len(result['edges'])}条已确认且已关联全文的有向关系、{len(result['components'])}个弱连通分量。",
            'scope': 'PageRank阻尼系数0.85，沿施引文献指向被引文献计算；只反映当前项目已确认的连接，不代表全网影响力、论文质量或研究新颖性。孤立节点不能据此判断为边缘研究。'}


def mermaid(data):
    aliases = {d['id']: f'n{i}' for i, d in enumerate(data['nodes'])}
    lines = ['flowchart LR']
    for doc in data['nodes']:
        # Encode all punctuation to prevent labels from injecting Mermaid syntax.
        label = ''.join(c if c.isalnum() or c == ' ' else f'#{ord(c)};' for c in doc['title'][:100])
        lines.append(f'  {aliases[doc["id"]]}["{label}"]')
    lines += [f'  {aliases[e["source"]]} --> {aliases[e["target"]]}' for e in data['edges']]
    return '\n'.join(lines) + '\n'


@router.get('/projects/{pid}/graph-insights/mermaid')
def graph_script(pid: str):
    return Response(mermaid(insights(pid)), media_type='text/plain; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="citation-network.mmd"'})


FUTURE = re.compile(r'future\s+(?:work|research|directions?)|further\s+(?:work|research)|未来工作|未来研究|后续研究|研究展望', re.I)


@router.get('/projects/{pid}/future-work')
def future_work(pid: str):
    core.project(pid)
    with core.db() as conn:
        docs = conn.execute('SELECT id,title,spans,matrix FROM documents WHERE project_id=? ORDER BY created,id', (pid,)).fetchall()
    items, truncated = [], False
    for row in docs:
        doc = {**dict(row), 'spans': json.loads(row['spans'])}
        following = 0
        for span in spans(doc):
            matched = bool(FUTURE.search(span['text']))
            if span.get('kind') == 'heading' and not matched:
                following = 0
            if matched or following:
                if len(items) >= 60:
                    truncated = True
                    break
                items.append({'document_id': doc['id'], 'title': doc['title'], **span,
                              'reason': '包含展望词句' if matched else '展望标题后的原文'})
            heading_only = re.fullmatch(r'\s*(?:\d[\d.]*\s*)?(?:future\s+(?:work|research|directions?)|未来工作|未来研究|后续研究|研究展望)\s*[:：]?\s*', span['text'], re.I)
            if matched and (span.get('kind') == 'heading' or heading_only):
                following = 2
            elif following:
                following -= 1
        if truncated:
            break
    return {'items': items, 'truncated': truncated,
            'scope': '按展望词句和标题提取原文候选，最多60段；不判断这些问题是否仍未解决。需结合后续文献和实验核对。'}


class OutlineBody(BaseModel):
    idea: str = Field(min_length=1, max_length=1000)
    document_ids: list[str] = Field(min_length=1, max_length=15)


@router.post('/projects/{pid}/literature-outline')
def create_outline(pid: str, body: OutlineBody):
    from .writing_drafts import Citation, DraftBody, create_draft
    core.project(pid)
    if not body.idea.strip() or len(set(body.document_ids)) != len(body.document_ids):
        raise HTTPException(422, '请填写研究想法，并选择不重复的文献')
    citations, materials = [], []
    for index, did in enumerate(body.document_ids, 1):
        doc = document(pid, did)
        # Prefer an explicitly labeled abstract; otherwise expose the first passage as such.
        first, chosen, after_abstract = None, None, False
        for span in spans(doc):
            if re.fullmatch(r'\s*(?:\d+\.?\s*)?(?:abstract|摘要)\s*[:：]?\s*', span['text'], re.I):
                after_abstract = True
                continue
            if span.get('kind') == 'heading':
                after_abstract = False
            else:
                first = first or span
                if after_abstract:
                    chosen = span
                    break
            if re.search(r'\babstract\b|摘要', span['text'], re.I):
                chosen = span
                break
        chosen = chosen or first
        if not chosen:
            raise HTTPException(422, f'“{doc["title"]}”还没有可引用原文，请等待解析完成')
        alias = f'paper{index}'
        citations.append(Citation(alias=alias, document_id=did, span_id=chosen['id']))
        # Display titles as plain prose; author-provided content is never a template directive.
        title = re.sub(r'[\[\]{}#*`<>\\]', ' ', doc['title']).replace('\n', ' ')
        materials.append(f'- {title} [[cite:{alias}]]：待作者核对研究任务、方法与局限；此处仅绑定原文片段。')
    idea = body.idea.strip().replace('{{', '｛｛').replace('[[cite:', '［［cite:')
    template = f'''## Abstract

研究想法：{idea}

待作者填写：问题、方法、真实结果与适用范围。没有实验结果时不得补写性能结论。

## Introduction

待作者填写：研究背景、具体问题、可检验预期与贡献；每个事实判断应补充对应来源。

## Related Work

以下是选定全文的阅读提纲，不是自动生成的综述结论：

{chr(10).join(materials)}

## Method

待作者填写：输入、处理步骤、对照因素与实现条件。

## Experiments

待作者填写：数据划分、评价指标、硬件与依赖、随机种子，以及成功运行的指标引用。

## Limitations and Future Work

待作者填写：已观察到的失败、适用边界与后续验证；展望候选需核对是否已被后续工作解决。

## References

所选原文的篇名、页码和逐字引文见“文献原文依据”。作者、年份、出版物及DOI需由作者核对补齐；未伪造缺失书目信息。
'''
    return create_draft(pid, DraftBody(title=('研究框架 · ' + body.idea.strip())[:100], template=template, citations=citations))
