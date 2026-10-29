"""Two sparse retrieval routes, reciprocal-rank fusion, per-document coverage.

This is not pretrained dense embedding retrieval. All returned excerpts are real.
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


ALIASES = {
    '方法': 'method architecture algorithm approach', '数据': 'dataset corpus samples data',
    '划分': 'train training validation test split', '种子': 'seed seeds random reproducibility',
    '硬件': 'GPU hardware NVIDIA V100 A100 memory', '参数': 'hyperparameter learning rate beta batch size',
    '指标': 'accuracy F1 BLEU evaluation metrics score', '局限': 'limitation future work',
    '代码': 'code implementation github source', '标准化': 'normalization standardization scaler',
}


def expand(query):
    return query + ' ' + ' '.join(v for k, v in ALIASES.items() if k in query)


def tokens(text):
    latin = re.findall(r'[a-z0-9_]+', text.lower())
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    return latin + [s[i:i + 2] for s in chinese for i in range(max(1, len(s) - 1))]


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
