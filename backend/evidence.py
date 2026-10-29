"""Source-only retrieval stage; returns original passages without generated answers."""
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from . import app as core
from .documents import document, project
from .retrieval import SparseIndex

router = APIRouter(prefix='/api')


@router.get('/projects/{pid}/evidence-search')
def search(pid: str, q: str = Query(min_length=2, max_length=200), document_id: str = ''):
    project(pid)
    if len(q.strip()) < 2:
        raise HTTPException(422, '请填写至少两个字符的研究问题或关键词')
    if document_id:
        selected = [document(pid, document_id)]
    else:
        with core.db() as conn:
            selected = [dict(r) for r in conn.execute('SELECT id,title,spans FROM documents WHERE project_id=? ORDER BY rowid', (pid,))]
    passages, characters = [], 0
    for doc in selected:
        counts = {}
        for span in json.loads(doc['spans']):
            characters += len(span['text'])
            if characters > 2000000 or len(passages) >= 5000:
                raise HTTPException(422, '本次检索超过5000段或200万字符，请先选择单篇文献；不会截断后冒充全文检索')
            index = counts.get(span['page'], 0)
            passages.append({**span, 'document_id': doc['id'], 'title': doc['title'], 'offset': index // 100 * 100})
            counts[span['page']] = index + 1
    items = SparseIndex(passages).search(q.strip(), limit=12)
    return {'query': q.strip(), 'items': items, 'searched_documents': len(selected), 'searched_passages': len(passages),
            'scope': '字符与词项TF-IDF检索并融合排序，最多显示12条原文候选；未生成模型答案。候选可能不支持问题，未命中不代表全文未报告。'}


@router.get('/projects/{pid}/evidence-search/export')
def export(pid: str, q: str = Query(min_length=2, max_length=200), document_id: str = ''):
    return Response(json.dumps(search(pid, q, document_id), ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="evidence-passages.json"'})
