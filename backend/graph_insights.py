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
