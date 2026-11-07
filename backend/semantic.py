"""Explicit local multilingual indexing; evidence remains linked to original spans."""
from concurrent.futures import ThreadPoolExecutor
import os
import re
import threading

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import app as core
from .ingestion import document, decorate, spans
from .retrieval import retrieve

router = APIRouter(prefix='/api')
MODEL_NAME = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MODEL, TOKENIZER, REVISION = None, None, ''
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='semantic')
PREPARING, ERROR = False, ''
with core.db() as conn:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS semantic_indexes(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,status TEXT NOT NULL,completed INTEGER NOT NULL,total INTEGER NOT NULL,model_revision TEXT NOT NULL,error TEXT NOT NULL,updated TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS semantic_passages(document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,span_id TEXT NOT NULL,part INTEGER NOT NULL,text TEXT NOT NULL,vector BLOB NOT NULL,PRIMARY KEY(document_id,span_id,part));
    ''')
    conn.execute("UPDATE semantic_indexes SET status='interrupted',error='服务停止，请重新建立索引' WHERE status IN ('queued','running')")


def prepare():
    global MODEL, TOKENIZER, REVISION, PREPARING, ERROR
    try:
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer
        cache = core.DATA / 'semantic-model'
        os.environ.setdefault('HF_HOME', str(cache / 'hub-home'))
        with LOCK:
            try:
                model = TextEmbedding(MODEL_NAME, cache_dir=str(cache), threads=2, providers=['CPUExecutionProvider'], local_files_only=True)
            except Exception:
                model = TextEmbedding(MODEL_NAME, cache_dir=str(cache), threads=2, providers=['CPUExecutionProvider'])
            tokenizer = Tokenizer.from_str(model.model.tokenizer.to_str())
            tokenizer.no_truncation(); tokenizer.no_padding()
            MODEL, TOKENIZER = model, tokenizer
            REVISION = model.model._model_dir.name  # Upstream model revision.
            ERROR = ''
    except Exception as exc:
        ERROR = f'本地模型未准备成功（{type(exc).__name__}），可检查网络后重试；关键词检索仍可用。'
    finally:
        PREPARING = False


@router.post('/semantic/prepare')
def prepare_model():
    global PREPARING
    with LOCK:
        if not PREPARING and MODEL is None:
            PREPARING = True
            POOL.submit(prepare)
    return {'preparing': PREPARING, 'ready': MODEL is not None}


@router.get('/projects/{pid}/semantic-indexes')
def indexes(pid: str):
    core.project(pid)
    with core.db() as conn:
        rows = [dict(r) for r in conn.execute('SELECT i.* FROM semantic_indexes i JOIN documents d ON d.id=i.document_id WHERE d.project_id=?', (pid,))]
    return {'ready': MODEL is not None, 'preparing': PREPARING, 'error': ERROR, 'model': MODEL_NAME, 'revision': REVISION, 'indexes': rows}


def chunk_passage(text):
    # Sentence boundaries prevent unrelated neighboring statements diluting a hit.
    for sentence in re.finditer(r'.+?(?:[.!?。！？](?:\s+|$)|\n|$)', text, re.S):
        value = sentence.group()
        offsets = TOKENIZER.encode(value, add_special_tokens=False).offsets
        for i in range(0, len(offsets), 100):
            group = offsets[i:i + 120]
            if group:
                piece = value[group[0][0]:group[-1][1]]
                if piece.strip():
                    yield piece
            if i + 120 >= len(offsets):
                break


def update(did, **values):
    with core.db() as conn:
        conn.execute('UPDATE semantic_indexes SET ' + ','.join(k + '=?' for k in values) + ',updated=? WHERE document_id=?', [*values.values(), core.now(), did])


def build(pid, did):
    try:
        with core.db() as conn:
            if not conn.execute("UPDATE semantic_indexes SET status='running' WHERE document_id=? AND status='queued'", (did,)).rowcount:
                return
        doc = document(pid, did)
        pieces = []
        for span in spans(doc):
            for n, text in enumerate(chunk_passage(span['text'])):
                pieces.append((span['id'], n, text))
                if len(pieces) > 20000:
                    raise ValueError('全文超过20000个模型窗口，请按研究范围拆分资料后建立索引')
        update(did, total=len(pieces))
        rows = []
        for start in range(0, len(pieces), 32):
            with core.db() as conn:
                state = conn.execute('SELECT status FROM semantic_indexes WHERE document_id=?', (did,)).fetchone()
            if not state or state['status'] != 'running':
                return
            batch = pieces[start:start + 32]
            with LOCK:
                vectors = list(MODEL.embed([p[2] for p in batch], batch_size=32))
            for (sid, n, text), vector in zip(batch, vectors):
                vector = np.asarray(vector, dtype=np.float32)
                vector /= max(float(np.linalg.norm(vector)), 1e-12)
                rows.append((did, sid, n, text, vector.tobytes()))
            update(did, completed=len(rows))
        with core.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = conn.execute('SELECT status FROM semantic_indexes WHERE document_id=?', (did,)).fetchone()
            if not state or state['status'] != 'running':
                return
            conn.execute('DELETE FROM semantic_passages WHERE document_id=?', (did,))
            conn.executemany('INSERT INTO semantic_passages VALUES (?,?,?,?,?)', rows)
            conn.execute("UPDATE semantic_indexes SET status='ready',model_revision=?,updated=? WHERE document_id=?", (REVISION, core.now(), did))
    except Exception as exc:
        update(did, status='failed', error=str(exc)[:800])


@router.post('/projects/{pid}/documents/{did}/semantic-index')
def build_index(pid: str, did: str):
    doc = decorate(document(pid, did))
    if MODEL is None:
        raise HTTPException(409, '请先准备本地语义模型')
    if doc.get('ingestion', {}).get('status', 'completed') != 'completed':
        raise HTTPException(409, '请先完成全文解析，再建立语义索引')
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT status FROM semantic_indexes WHERE document_id=?', (did,)).fetchone()
        if old and old['status'] in {'queued', 'running'}:
            raise HTTPException(409, '这篇文献已在索引队列中')
        count = conn.execute("SELECT COUNT(*) FROM semantic_indexes WHERE status IN ('queued','running')").fetchone()[0]
        if count >= 6:
            raise HTTPException(429, '索引队列已有6篇全文，请稍后重试')
        conn.execute("INSERT INTO semantic_indexes VALUES (?,'queued',0,0,?,'',?) ON CONFLICT(document_id) DO UPDATE SET status='queued',completed=0,total=0,error='',updated=excluded.updated", (did, REVISION, core.now()))
    POOL.submit(build, pid, did)
    return indexes(pid)


@router.post('/projects/{pid}/documents/{did}/semantic-index/cancel')
def cancel_index(pid: str, did: str):
    document(pid, did)
    with core.db() as conn:
        conn.execute("UPDATE semantic_indexes SET status='cancelled' WHERE document_id=? AND status IN ('queued','running')", (did,))
    return indexes(pid)


class SearchBody(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    document_ids: list[str] = Field(min_length=1, max_length=8)
    hybrid: bool = True


class DuplicateBody(BaseModel):
    document_ids: list[str] = Field(min_length=2, max_length=8)


@router.post('/projects/{pid}/semantic-duplicates')
def semantic_duplicates(pid: str, body: DuplicateBody):
    if len(set(body.document_ids)) != len(body.document_ids):
        raise HTTPException(422, '请选择不重复的文献')
    docs = [document(pid, did) for did in body.document_ids]
    vectors, texts = {}, {}
    total = 0
    with core.db() as conn:
        for doc in docs:
            state = conn.execute('SELECT * FROM semantic_indexes WHERE document_id=?', (doc['id'],)).fetchone()
            if not state or state['status'] != 'ready' or state['model_revision'] != REVISION or not REVISION:
                raise HTTPException(409, '请先为所选文献建立同一模型版本的完整语义索引')
            count = conn.execute('SELECT COUNT(*) FROM semantic_passages WHERE document_id=?', (doc['id'],)).fetchone()[0]
            total += count
            if total > 8000:
                raise HTTPException(422, '本轮超过8000个语义窗口，请缩小比较范围；不会截断后判断版本')
            rows = conn.execute('SELECT text,vector FROM semantic_passages WHERE document_id=? ORDER BY span_id,part', (doc['id'],)).fetchall()
            if not rows:
                raise HTTPException(409, '语义索引没有可比较的窗口，请重新建立')
            vectors[doc['id']] = np.stack([np.frombuffer(r['vector'], dtype=np.float32) for r in rows])
            texts[doc['id']] = [r['text'] for r in rows]
    pairs = []
    for index, first in enumerate(docs):
        for second in docs[index+1:]:
            a, b = vectors[first['id']], vectors[second['id']]
            best_a, best_b, witnesses = [], np.full(len(b), -1., dtype=np.float32), []
            for start in range(0, len(a), 64):
                similarities = np.clip(a[start:start+64] @ b.T, -1, 1)
                maxima = similarities.max(axis=1)
                best_a.extend(maxima.tolist())
                best_b = np.maximum(best_b, similarities.max(axis=0))
                for offset, score in enumerate(maxima):
                    witnesses.append((float(score), start+offset, int(similarities[offset].argmax())))
            coverage_a = sum(s >= .88 for s in best_a)/len(a)
            coverage_b = float(np.mean(best_b >= .88))
            score = (float(np.mean(best_a))+float(np.mean(best_b)))/2
            examples, used = [], set()
            for similarity, ai, bi in sorted(witnesses, reverse=True):
                if bi in used:
                    continue
                examples.append({'similarity': round(similarity, 4), 'first': texts[first['id']][ai], 'second': texts[second['id']][bi]})
                used.add(bi)
                if len(examples) == 3:
                    break
            pairs.append({'first_id': first['id'], 'second_id': second['id'], 'similarity': round(score, 4),
                          'first_coverage': round(coverage_a, 4), 'second_coverage': round(coverage_b, 4),
                          'candidate': min(coverage_a, coverage_b) >= .65, 'examples': examples})
    return {'pairs': sorted(pairs, key=lambda p: p['similarity'], reverse=True), 'windows': total,
            'model': MODEL_NAME, 'revision': REVISION,
            'scope': '比较完整索引窗口的双向最近语义相似度；覆盖率为相似度≥0.88的窗口比例。双向覆盖均≥65%时提示候选，这是经验阈值，不是重复概率。相关主题也可能相近，需核对正文差异与版本日期；不自动合并、删除或替换。'}


@router.post('/projects/{pid}/semantic-search')
def search(pid: str, body: SearchBody):
    if not body.question.strip():
        raise HTTPException(422, '请填写检索问题')
    docs = [document(pid, did) for did in dict.fromkeys(body.document_ids)]
    if MODEL is None:
        raise HTTPException(409, '本地语义模型尚未准备好')
    if len(TOKENIZER.encode(body.question, add_special_tokens=False).ids) > 120:
        raise HTTPException(422, '问题超过120个模型词元，请缩短；系统不会静默截断问题')
    with core.db() as conn:
        for doc in docs:
            state = conn.execute('SELECT * FROM semantic_indexes WHERE document_id=?', (doc['id'],)).fetchone()
            if not state or state['status'] != 'ready' or state['model_revision'] != REVISION:
                raise HTTPException(409, '所选全文中有未完成或模型版本不同的索引，请重新建立后检索')
        selection = ' WHERE document_id IN (' + ','.join('?' for _ in docs) + ')'
        ids = [d['id'] for d in docs]
        if conn.execute('SELECT COUNT(*) FROM semantic_passages' + selection, ids).fetchone()[0] > 32000:
            raise HTTPException(422, '所选索引超过32000个窗口，请减少文献数量后检索')
        rows = conn.execute('SELECT * FROM semantic_passages' + selection, ids).fetchall()
    with LOCK:
        vector = np.asarray(next(MODEL.embed([body.question])), dtype=np.float32)
    vector /= max(float(np.linalg.norm(vector)), 1e-12)
    candidates = {}
    for row in rows:
        score = float(np.dot(vector, np.frombuffer(row['vector'], dtype=np.float32)))
        key = (row['document_id'], row['span_id'])
        if key not in candidates or score > candidates[key]['similarity']:
            candidates[key] = {'similarity': score, 'matched_text': row['text']}
    known = {(d['id'], s['id']): {**s, 'document_id': d['id'], 'title': d['title'], 'citation': d['id'] + ':' + s['id']} for d in docs for s in spans(d)}
    scores = {}
    for rank, (key, value) in enumerate(sorted(candidates.items(), key=lambda x: x[1]['similarity'], reverse=True)[:30], 1):
        if key in known:
            scores[key] = {**known[key], **value, 'score': 1 / (60 + rank), 'routes': ['semantic']}
    if body.hybrid:
        for rank, hit in enumerate(retrieve(docs, body.question, 30), 1):
            key = (hit['document_id'], hit['id'])
            if key not in scores:
                scores[key] = {**hit, 'score': 0, 'routes': []}
            scores[key]['score'] += 1 / (60 + rank)
            scores[key]['routes'].append('keyword')
    return {'evidence': sorted(scores.values(), key=lambda x: x['score'], reverse=True)[:12], 'model': MODEL_NAME, 'revision': REVISION, 'note': '语义相似度和融合排名不是事实置信度；候选可能无关，解释与引用仍需核对原文。索引按句切分，长句使用最多120个词元的重叠窗口。'}
