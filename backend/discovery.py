"""Explicit searches against public scholarly metadata services."""
import json
import time
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query

from . import app as core
from pydantic import BaseModel, Field
class MetadataBody(BaseModel):
    doi: str = Field(default='', max_length=300)


router = APIRouter(prefix='/api')


def public_json(url, params=None):
    try:
        with httpx.Client(timeout=25, follow_redirects=False) as client:
            with client.stream('GET', url, params=params, headers={'User-Agent': 'ResearchWorkbench/0.1'}) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise HTTPException(502, '题录响应超过2MB，请缩小检索范围')
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, '题录服务暂时不可用或限制访问，请稍后重试')


def crossref_metadata(row):
    dates = row.get('published', {}).get('date-parts', [[]])
    return {'title': (row.get('title') or ['无题名'])[0], 'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) for a in row.get('author', [])[:100]],
            'year': str(dates[0][0]) if dates and dates[0] else '', 'venue': (row.get('container-title') or [''])[0], 'doi': row.get('DOI',''), 'url': row.get('URL',''),
            'kind': 'C' if row.get('type') == 'proceedings-article' else 'J', 'volume': row.get('volume',''), 'issue': row.get('issue',''), 'pages': row.get('page',''), 'publisher': row.get('publisher','')}


@router.get('/literature/discover')
def discover(q: str = Query(min_length=2,max_length=300), provider: Literal['crossref','arxiv','pubmed'] = 'crossref'):
    if not q.strip():
        raise HTTPException(422, '请填写研究关键词或题名')
    if provider == 'arxiv':
        from .paper_watch import download, parse_feed, query_params
        rows = parse_feed(download('https://export.arxiv.org/api/query', 2*1024*1024, params=query_params(q)))
        items = [{**r, 'year': r['published'][:4], 'source': 'arXiv'} for r in rows]
    elif provider == 'crossref':
        data = public_json('https://api.crossref.org/works', {'query': q, 'rows': 12})
        items = [{**crossref_metadata(row), 'source': 'Crossref'} for row in data.get('message', {}).get('items', [])]
    else:
        endpoint = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
        data = public_json(endpoint+'esearch.fcgi', {'db':'pubmed','term':q,'retmode':'json','retmax':12})
        ids = data.get('esearchresult', {}).get('idlist', [])
        if not isinstance(ids, list) or any(not str(i).isdigit() for i in ids):
            raise HTTPException(502, 'PubMed返回无效标识')
        time.sleep(.35)
        rows = public_json(endpoint+'esummary.fcgi', {'db':'pubmed','id':','.join(ids),'retmode':'json'}).get('result', {}) if ids else {}
        items = [{'title': rows[i].get('title',''), 'authors':[a.get('name','') for a in rows[i].get('authors', [])], 'year':rows[i].get('pubdate','')[:4], 'venue':rows[i].get('fulljournalname',''),
                  'doi': next((a['value'] for a in rows[i].get('articleids', []) if a.get('idtype') == 'doi'), ''), 'url':f'https://pubmed.ncbi.nlm.nih.gov/{i}/', 'source':'PubMed'} for i in ids if isinstance(rows.get(i), dict)]
    return {'items':items, 'provider':provider, 'retrieved':core.now(), 'scope':'外部题录不是项目全文；获取并导入原件后才能作为原文依据。下载入口仅使用arXiv官方服务，其他来源由作者取得合法全文。'}


@router.post('/projects/{pid}/documents/{did}/metadata-resolve')
def resolve_metadata(pid: str, did: str, body: MetadataBody):
    from .ingestion import document
    from .references import DOI
    document(pid, did)
    identifier = body.doi.removeprefix('https://doi.org/').strip()
    if not DOI.fullmatch(identifier):
        raise HTTPException(422, '请先填写有效DOI')
    row = public_json('https://api.crossref.org/works/'+quote(identifier,safe='')).get('message')
    if not isinstance(row,dict):
        raise HTTPException(502, '未取得可用题录')
    return crossref_metadata(row)
