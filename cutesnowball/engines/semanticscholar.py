"""Semantic Scholar Graph API adapter — free, generous, no blocking.

S2 exposes dedicated `/paper/DOI:{doi}/citations` and `/paper/DOI:{doi}/references`
endpoints that paginate fully (unlike the nested `?fields=` form which is
silently capped).  No API key required for low volume (100 req / 5 min
anonymous).

Mirrors the `s2PagedList` technique from BackwardForwardSnowballing's api.js.
"""
from __future__ import annotations

import time
from typing import List, Optional

from ..config import config
from ..models import Paper
from ..rate_limiter import rate_limiter
from .base import CitationAdapter

S2 = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,externalIds,authors,year,abstract,venue,citationCount,openAccessPdf,url"
CITE_FIELDS = "title,externalIds,authors,year,citationCount,venue"


def _authors(authors) -> str:
    out = []
    for a in (authors or [])[:20]:
        name = (a or {}).get("name") or ""
        if name:
            out.append(name)
    return "; ".join(out)


def _s2_to_paper(obj: dict, source_tag: str = "semantic_scholar") -> Paper:
    ext = obj.get("externalIds") or {}
    doi = (ext.get("DOI") or "").lower() or None
    if doi:
        doi = doi.replace("https://doi.org/", "").strip().lower() or None
    sid = obj.get("paperId")
    oap = obj.get("openAccessPdf") or {}
    pdf = (oap.get("url") if isinstance(oap, dict) else None) or ""
    return Paper(
        title=obj.get("title") or "",
        doi=doi,
        authors=_authors(obj.get("authors")),
        year=obj.get("year"),
        abstract=obj.get("abstract") or "",
        venue=obj.get("venue") or "",
        num_citations=int(obj.get("citationCount") or 0),
        sources=[source_tag],
        scholar_id=sid,
        url=obj.get("url") or "",
        pdf_url=pdf,
    )


class SemanticScholarAdapter(CitationAdapter):
    name = "semantic_scholar"

    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        if doi:
            url = f"{S2}/paper/DOI:{doi}?fields={FIELDS}"
            status, data = rate_limiter.get_json(url)
            if status == 200 and data:
                return _s2_to_paper(data)
        if title:
            url = f"{S2}/paper/search"
            params = {"query": title, "limit": 1, "fields": FIELDS}
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                items = (data or {}).get("data") or []
                if items:
                    return _s2_to_paper(items[0])
        return None

    def backward(self, paper: Paper) -> List[Paper]:
        if not paper.doi and not paper.scholar_id:
            return []
        return self._paged(paper, "references")

    def forward(self, paper: Paper) -> List[Paper]:
        if not paper.doi and not paper.scholar_id:
            return []
        return self._paged(paper, "citations")

    def _paged(self, paper: Paper, kind: str) -> List[Paper]:
        """kind in {'citations','references'} — paginated endpoint."""
        if paper.scholar_id:
            base = f"{S2}/paper/{paper.scholar_id}/{kind}"
        elif paper.doi:
            base = f"{S2}/paper/DOI:{paper.doi}/{kind}"
        else:
            return []
        out: List[Paper] = []
        offset = 0
        limit = 1000
        for _ in range(config.max_s2_pages):
            params = {"fields": CITE_FIELDS, "offset": offset, "limit": limit}
            status, data = rate_limiter.get_json(base, params=params)
            if status != 200 or not data:
                break
            items = data.get("data") or []
            if not items:
                break
            for entry in items:
                # S2 nests the actual paper under 'citingPaper' or 'citedPaper'
                inner = entry.get("citingPaper") or entry.get("citedPaper") or entry
                if inner and inner.get("paperId"):
                    out.append(_s2_to_paper(inner))
            if len(items) < limit:
                break
            offset += limit
            time.sleep(config.page_delay_ms / 1000.0)
        return out

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        url = f"{S2}/paper/search"
        params = {"query": query, "limit": min(limit, 100), "fields": FIELDS}
        status, data = rate_limiter.get_json(url, params=params)
        if status != 200 or not data:
            return []
        out = []
        for it in (data or {}).get("data") or []:
            out.append(_s2_to_paper(it))
        return out[:limit]
