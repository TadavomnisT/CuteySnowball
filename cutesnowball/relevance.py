"""Relevance scoring for snowball candidates.

Implements a weighted, pure-Python relevance score (no scikit-learn):

    relevance(c) = w_tfidf   * cos_tfidf(seed_corpus, c)
                 + w_keyword * jaccard(seed_keywords, c.title+abstract)
                 + w_recency * recency(c.year)
                 + w_cite    * norm_cite(c.num_citations)

All weights live in `Config.source_weights()` and default to
(0.45, 0.25, 0.15, 0.15) — a deliberately IR-conservative blend that
ranks semantic similarity highest while still rewarding fresh, well-cited
work.

The TF-IDF is implemented from scratch (no external dependency): tokens are
lowercased alphanumerics >=3 chars, stopwords removed, bigrams not used
(to keep it simple).  Cosine similarity over the resulting sparse vectors.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Set, Tuple

from .config import config
from .models import Paper

# A small English stoplist so the score isn't dominated by "the", "of", etc.
_STOP = set(
    "a an the of to in on for with and or but not is are was were be been "
    "by this that these those it as at from which their its his her our your "
    "we they you i he she them us our my your into over under between among "
    "than then so such only also more most some any all can could may might "
    "must should would will shall do does did done has have had having "
    "about above after again against because before below during each few "
    "here how itself no nor now off other out own same there what when where "
    "who whom why via using based using per etc".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{2,}")


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


def keywords_of(paper: Paper) -> Set[str]:
    """Salient single tokens of a paper (title weighted 3x)."""
    text = (paper.title + " ") * 3 + paper.abstract
    return set(tokenize(text))


class TfidfModel:
    """Minimal TF-IDF model fit on the seed corpus."""

    def __init__(self):
        self.vocab: Dict[str, int] = {}
        self.idf: List[float] = []
        self.seed_vecs: List[Tuple[Dict[int, float], float]] = []
        self.seed_norm: float = 0.0

    def fit(self, seeds: Sequence[Paper]):
        docs = [tokenize((p.title or "") + " " + (p.abstract or "")) for p in seeds]
        df = Counter()
        for d in docs:
            for w in set(d):
                df[w] += 1
        n = len(docs) or 1
        self.vocab = {w: i for i, w in enumerate(sorted(df))}
        self.idf = [
            math.log((1 + n) / (1 + df[w])) + 1.0 for w in sorted(df)
        ]
        self.seed_vecs = [self._vec(d) for d in docs]
        # average seed vector
        if self.seed_vecs:
            agg: Dict[int, float] = {}
            for vec, _ in self.seed_vecs:
                for k, v in vec.items():
                    agg[k] = agg.get(k, 0.0) + v
            for k in agg:
                agg[k] /= len(self.seed_vecs)
            self._avg_vec = agg
            self._avg_norm = math.sqrt(sum(v * v for v in agg.values())) or 1.0
        else:
            self._avg_vec = {}
            self._avg_norm = 1.0

    def _vec(self, tokens: List[str]) -> Tuple[Dict[int, float], float]:
        tf = Counter(tokens)
        vec: Dict[int, float] = {}
        for w, c in tf.items():
            idx = self.vocab.get(w)
            if idx is None:
                continue
            vec[idx] = (1.0 + math.log(c)) * self.idf[idx]
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return vec, norm

    def cosine_vs_seed(self, text: str) -> float:
        tokens = tokenize(text)
        vec, norm = self._vec(tokens)
        if norm == 0 or self._avg_norm == 0:
            return 0.0
        # dot product
        small, large = (vec, self._avg_vec) if len(vec) < len(self._avg_vec) else (self._avg_vec, vec)
        dot = 0.0
        for k, v in small.items():
            w = large.get(k)
            if w is not None:
                dot += v * w
        return dot / (norm * self._avg_norm)


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter) if (len(a) + len(b) - inter) else 0.0


def _recency(year: int | None) -> float:
    if not year:
        return 0.0
    return 1.0 - math.exp(-(year - config.recency_ref_year) / config.recency_tau)


def _norm_cite(n: int) -> float:
    if n <= 0:
        return 0.0
    # log1p saturation: a 1000-cite paper ~= a 100-cite paper
    return min(1.0, math.log1p(n) / math.log1p(1000))


class RelevanceScorer:
    def __init__(self, seeds: Sequence[Paper], w: Dict[str, float] | None = None):
        self.seeds = list(seeds)
        self.w = w or config.source_weights()
        self.tfidf = TfidfModel()
        self.tfidf.fit(self.seeds)
        self.seed_kw: Set[str] = set()
        for p in self.seeds:
            self.seed_kw |= keywords_of(p)

    def score(self, paper: Paper) -> float:
        text = (paper.title or "") + " " + (paper.abstract or "")
        cos = self.tfidf.cosine_vs_seed(text)
        kw = keywords_of(paper)
        jac = jaccard(self.seed_kw, kw)
        rec = _recency(paper.year)
        cit = _norm_cite(paper.num_citations)
        score = (
            self.w.get("tfidf", 0.0) * cos
            + self.w.get("keyword", 0.0) * jac
            + self.w.get("recency", 0.0) * rec
            + self.w.get("citations", 0.0) * cit
        )
        return round(max(0.0, min(1.0, score)), 4)

    def explain(self, paper: Paper) -> Dict:
        """Return a per-term breakdown of the relevance score for the UI."""
        text = (paper.title or "") + " " + (paper.abstract or "")
        cos = self.tfidf.cosine_vs_seed(text)
        kw = keywords_of(paper)
        jac = jaccard(self.seed_kw, kw)
        rec = _recency(paper.year)
        cit = _norm_cite(paper.num_citations)
        w = self.w
        terms = {
            "tfidf": {"raw": round(cos, 4), "weight": w.get("tfidf", 0.0), "contribution": round(w.get("tfidf", 0.0) * cos, 4)},
            "keyword": {"raw": round(jac, 4), "weight": w.get("keyword", 0.0), "contribution": round(w.get("keyword", 0.0) * jac, 4)},
            "recency": {"raw": round(rec, 4), "weight": w.get("recency", 0.0), "contribution": round(w.get("recency", 0.0) * rec, 4)},
            "citations": {"raw": round(cit, 4), "weight": w.get("citations", 0.0), "contribution": round(w.get("citations", 0.0) * cit, 4)},
        }
        total = sum(t["contribution"] for t in terms.values())
        # top overlapping keywords
        overlap = sorted(self.seed_kw & kw, key=lambda k: -len(k))[:12]
        # TF-IDF top contributing tokens (for highlight in abstract)
        top_tokens = self._top_tfidf_tokens(text, limit=12)
        return {
            "total": round(max(0.0, min(1.0, total)), 4),
            "terms": terms,
            "overlap_keywords": overlap,
            "top_tokens": top_tokens,
            "seed_keyword_count": len(self.seed_kw),
            "paper_keyword_count": len(kw),
        }

    def _top_tfidf_tokens(self, text: str, limit: int = 12) -> List[str]:
        """Return the tokens in `text` that have the highest TF-IDF weight
        (i.e. the tokens most responsible for the cosine similarity to the seed)."""
        toks = tokenize(text)
        scored = []
        for w in set(toks):
            idx = self.tfidf.vocab.get(w)
            if idx is None:
                continue
            # tf-idf weight of this token in the candidate
            tf = toks.count(w)
            weight = (1.0 + math.log(tf)) * self.tfidf.idf[idx] if tf > 0 else 0
            scored.append((w, weight))
        scored.sort(key=lambda x: -x[1])
        return [w for w, _ in scored[:limit]]

    def score_many(self, papers: Sequence[Paper]) -> None:
        for p in papers:
            p.relevance = self.score(p)
