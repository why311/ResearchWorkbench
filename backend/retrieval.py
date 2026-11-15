"""Two sparse retrieval routes, reciprocal-rank fusion, per-document coverage.

This is not pretrained dense embedding retrieval. All returned excerpts are real.
"""
import re
import unicodedata
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import app as core

ALIASES = {
    '方法': 'method architecture algorithm approach', '数据': 'dataset corpus samples data',
    '划分': 'train training validation test split', '种子': 'seed seeds random reproducibility',
    '硬件': 'GPU hardware NVIDIA V100 A100 memory', '参数': 'hyperparameter learning rate beta batch size',
    '指标': 'accuracy F1 BLEU evaluation metrics score', '局限': 'limitation future work',
    '代码': 'code implementation github source', '标准化': 'normalization standardization scaler',
    '掩码': 'mask masking subsequent positions future tokens causal', 'masking': 'mask masked subsequent positions',
    '双向': 'bidirectional left right context', 'bidirectional': 'both left right context',
    '显存': 'GPU memory memory footprint', '冻结': 'freeze frozen weights pretrained parameters',
    '优化器状态': 'optimizer states', '梯度': 'gradients', '分片': 'partition partitioning sharding',
    '训练目标': 'training objective pretraining loss', '图文对比': 'image text contrastive learning paired caption',
}


FACT_PATTERNS = (
    (r'context\s+(?:window|size|length)|sequence\s+length|上下文(?:窗口|长度)|序列长度',
     r'(?:context\s+(?:window|size|length)|contiguous\s+sequences?|(?:model|training)\s+sequence\s+length|上下文(?:窗口|长度))'
     r'[^.!?。]{0,90}\d[\d,]*\s*(?:tokens?|词元|标记)'),
    (r'(?:parameter|param)[ -]?(?:count|size)|(?:number|count)\s+of\s+(?:\w+\s+)?parameters|'
     r'(?:how many|model)\s+parameters|参数(?:总量|量|规模|数量)',
     r'(?<!\w)\d+(?:\.\d+)?\s*(?:(?:[MB]\b)|(?:million|billion)\s+parameters|亿参数|万参数)'),
    (r'layer\s*norm(?:alization)?|pre[\s-]norm(?:alization)?|归一化',
     r'(?:layer\s*norm(?:alization)?|归一化)[^.!?。]{0,100}(?:moved|input|before|after|residual|子层|残差)|'
     r'pre[-\s]+normalization|\bnorm\(\s*\w+\s*\+\s*\w+'),
    (r'optimizer\s+states?|优化器状态|\bshard(?:ing|ed)?\b|分片|frozen\s+(?:weights|parameters)|冻结',
     r'\b(?:freeze[sd]?|frozen)\b[^.!?。]{0,110}\b(?:weights?|parameters?)\b|'
     r'\b(?:weights?|parameters?)\b[^.!?。]{0,85}\b(?:freeze[sd]?|frozen)\b|'
     r'\bpartitio(?:n\w*|ns)\b[^.!?。]{0,180}(?:optimizer\s+states?|gradients?|parameters?)'),
    (r'image\s+patch(?:es)?|vision transformer|图像切分|图像块|图文对比|image.text contrastive',
     r'\b(?:split|reshape|divide|sequence|flatten)\w*\b[^.!?。]{0,100}\bpatch(?:es)?\b|'
     r'\bcontrastive\b[^.!?。]{0,100}\b(?:image|text|loss|objective|caption)\b|'
     r'\bpredict\w*\b[^.!?。]{0,75}\bcaption\b[^.!?。]{0,50}\bimage\b'),
)


def factual_passages(documents, question):
    patterns = [re.compile(evidence, re.I) for ask, evidence in FACT_PATTERNS if re.search(ask, question, re.I)]
    if not patterns:
        return []
    requested_tables = set(re.findall(r'\bTable\s+(\d+(?:\.\d+)*)|表\s*(\d+(?:\.\d+)*)', question, re.I))
    requested_tables = {en or zh for en, zh in requested_tables}
    result = []
    for doc in documents:
        passages = list(core.document_spans(doc))
        best = {}
        for pattern in patterns:
            ranked = []
            for index, span in enumerate(passages):
                text = ' '.join(span['text'].split())
                matches = pattern.findall(text)
                if not matches:
                    continue
                same_page = [part['text'] for part in passages[max(0, index - 2):index + 3] if part['page'] == span['page']]
                nearby = ' '.join(same_page)
                specific_table = any(re.search(r'(?:\btable\s+|表\s*)' + re.escape(num) + r'(?!\d|\.\d)', nearby, re.I)
                                     for num in requested_tables)
                score = (10 if specific_table else 0) + min(len(matches), 6)
                ranked.append((score, index, span))
            for score, _, span in sorted(ranked, key=lambda item: (-item[0], item[1]))[:2]:
                best[span['id']] = (score, span)
        for score, span in sorted(best.values(), key=lambda item: -item[0]):
            result.append({**span, 'document_id': doc['id'], 'title': doc['title'],
                           'citation': f"{doc['id']}:{span['id']}", 'score': 0, 'routes': ['keyword']})
    return result


def expand(query):
    return query + ' ' + ' '.join(v for k, v in ALIASES.items() if k in query)


def tokens(text):
    latin = re.findall(r'[a-z0-9_]+', text.lower())
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    return latin + [s[i:i + 2] for s in chinese for i in range(max(1, len(s) - 1))]


def select_research_documents(documents, question, limit=8):
    """Route a broad library query using front matter before loading full text."""
    names = {word.lower() for word in re.findall(r'[A-Za-z][A-Za-z0-9-]{2,}', question)
             if sum(c.isupper() for c in word) >= 2}
    phrases = {p.lower() for p in re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3}\b', question)}
    summaries, exact_titles = [], []
    named, expanded = defaultdict(dict), defaultdict(dict)
    question_text = ' '.join(question.lower().split())
    for doc in documents:
        did = doc['id']
        front = '\n'.join(s['text'] for s in doc['spans'][:18] if s['page'] <= 2)[:4200]
        title = doc['title']
        acronyms = {word.lower() for word in re.findall(r'\(([A-Z][A-Za-z0-9-]{2,15})\)', front)}
        repos = {word.lower() for word in re.findall(r'github\.com/[\w.-]+/([\w-]+)', front, re.I)}
        title_names = set(re.findall(r'[a-z][a-z0-9-]{2,}', title.lower()))
        front_text = ' '.join(front.lower().split())
        normalized_title = ' '.join(title.lower().split()).strip(' .:')
        if (len(normalized_title.split()) >= 3 and normalized_title in question_text
                or doc['filename'].lower() in question_text):
            exact_titles.append(did)
        for word in names:
            if (word in title_names or word in repos or
                    re.search(r'\b' + re.escape(word) + r'\b', doc['filename'], re.I)):
                named[word][did] = (3, 0)
            elif word in acronyms:
                named[word][did] = (2, 0)
            elif '-' in word:
                mentions = len(re.findall(r'\b' + re.escape(word) + r'\b', front_text))
                if mentions > 1:
                    named[word][did] = (1, mentions)
        for phrase in phrases:
            if phrase in normalized_title or re.search(r'\b' + re.escape(phrase) + r'\s*\([a-z0-9-]{2,15}\)', front_text):
                expanded[phrase][did] = 2 if phrase == normalized_title else 1
        summaries.append({'id': did, 'text': f'{title}\n{title}\n{front}'})
    named_set = set(exact_titles)
    for scores in named.values():
        best = max(scores.values())
        named_set.update(did for did, score in scores.items() if score == best)
    if len(named_set) < 2:
        for scores in expanded.values():
            best = max(scores.values())
            named_set.update(did for did, score in scores.items() if score == best)
    # Multiple copies of the same arXiv paper should not consume a comparison's
    # evidence budget. Prefer the newest native PDF when the versions are known.
    variants = defaultdict(list)
    for doc in documents:
        match = re.fullmatch(r'(\d{4}\.\d{4,5})(?:v(\d+))?([_ -]img)?\.pdf', doc['filename'], re.I)
        if match and doc['id'] in named_set:
            variants[match[1]].append((int(match[2] or 0), not match[3], doc['id']))
    for base, copies in variants.items():
        requested = set(re.findall(re.escape(base) + r'v(\d+)', question_text))
        preferred = [row for row in copies if str(row[0]) in requested]
        keep = {row[2] for row in preferred} if preferred else {max(copies)[2]}
        named_set.difference_update(row[2] for row in copies if row[2] not in keep)
    ranked = [hit['id'] for hit in SparseIndex(summaries).search(question, len(documents))]
    ordered = sorted(ranked, key=lambda did: did not in named_set)
    selected = list(dict.fromkeys([*ordered, *(doc['id'] for doc in documents)]))[:limit]
    lookup = {doc['id']: doc for doc in documents}
    return [lookup[did] for did in selected], [lookup[did] for did in selected if did in named_set]


def matching_quote(source, quote):
    def normalize(text):
        text = unicodedata.normalize('NFC', text).replace('\u00ad', '')
        text = re.sub(r'(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)', '', text)
        text = text.translate(str.maketrans({'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬀ': 'ff', 'ﬃ': 'ffi', 'ﬄ': 'ffl'}))
        return ' '.join(text.split())
    if not isinstance(quote, str) or not quote.strip():
        return False
    normalized = normalize(quote)
    return bool(normalized and (quote in source or normalized in normalize(source)))


class SparseIndex:
    def __init__(self, passages):
        self.passages, self.routes = passages, []
        if not passages:
            return
        texts = [p['text'] for p in passages]
        for vectorizer in (TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=30000),
                           TfidfVectorizer(tokenizer=tokens, token_pattern=None, lowercase=False, sublinear_tf=True, max_features=30000)):
            try:
                self.routes.append((vectorizer, vectorizer.fit_transform(texts)))
            except ValueError:
                pass

    def search(self, query, limit=4):
        ranks = {}
        for vectorizer, matrix in self.routes:
            scores = cosine_similarity(vectorizer.transform([expand(query)]), matrix)[0]
            ordered = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            for rank, (index, score) in enumerate(ordered[:max(20, limit)], 1):
                if score > 0:
                    ranks[index] = ranks.get(index, 0) + 1 / (60 + rank)
        return [{**self.passages[i], 'score': round(float(score), 6)} for i, score in sorted(ranks.items(), key=lambda x: x[1], reverse=True)[:limit]]


def retrieve(documents, query, limit=8, per_document_limit=None):
    result = []
    for doc in documents:
        passages = [{'document_id': doc['id'], 'title': doc['title'], **s, 'citation': f"{doc['id']}:{s['id']}"} for s in core.document_spans(doc)]
        result.extend(SparseIndex(passages).search(query, per_document_limit or limit))
    return sorted(result, key=lambda x: x['score'], reverse=True)[:limit]
