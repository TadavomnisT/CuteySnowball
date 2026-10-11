"""OpenAlex adapter — free, no key, no blocking risk.

OpenAlex is the PRIMARY forward-snowballing source in CuteySnowball because:
  * It is fully open (no auth, no rate limit beyond politeness).
  * It supports cursor pagination (no hard cap) for `filter=cites:{id}`
    giving up to thousands of citing works.
  * It returns rich metadata: title, authors, year, abstract_inverted_index,
    referenced_works (OpenAlex IDs), publication_year, etc.
  * It supports batch DOI hydration: `filter=doi:a|b|c|...&per_page=50`.

This adapter mirrors the techniques from the BackwardForwardSnowballing
project's `api.js` (abequet/BackwardForwardSnowballing):
  * `fetchOpenAlexWork(doi)` -> work + referenced_works
  * `openAlexResolveByDOI(dois)` -> batch hydration 50 at a time
  * `fetchOpenAlexCiting(oaId)` -> cursor-paginated forward
  * `abstractFromInverted(inv)` -> reconstruct text from inverted index
"""
from __future__ import annotations

import time
import urllib.parse
from typing import List, Optional

from ..config import config
from ..models import Paper
from ..rate_limiter import rate_limiter
from .base import CitationAdapter

OPENALEX = "https://api.openalex.org"
# Fields we ask for in bulk work lookups.
WORK_SELECT = "id,doi,title,authorships,publication_year,referenced_works,abstract_inverted_index,cited_by_count,primary_location,type,open_access"
CITE_SELECT = "id,doi,title,authorships,publication_year,cited_by_count"


def _authors(authorships) -> str:
    """OpenAlex authorships -> 'Family, Given; Family, Given'."""
    out = []
    for a in (authorships or [])[:20]:
        au = (a or {}).get("author") or {}
        name = au.get("display_name") or ""
        if name:
            out.append(name)
    return "; ".join(out)


def _year(work) -> Optional[int]:
    y = work.get("publication_year")
    try:
        return int(y) if y else None
    except (TypeError, ValueError):
        return None


def _abstract_from_inverted(inv) -> str:
    """Reconstruct plain text from OpenAlex's inverted-index abstract."""
    if not inv:
        return ""
    pos = []  # (position, word)
    for word, positions in inv.items():
        for p in positions:
            pos.append((p, word))
    pos.sort()
    return " ".join(w for _, w in pos)


def _work_to_paper(work: dict, source_tag: str = "openalex") -> Paper:
    loc = (work.get("primary_location") or {}) or {}
    src = (loc.get("source") or {}) or {}
    best_oa = loc.get("pdf_url") or loc.get("landing_page_url") or ""
    oa = work.get("open_access") or {}
    pdf = oa.get("oa_url") or best_oa or ""
    p = Paper(
        title=work.get("title") or "",
        doi=(work.get("doi") or "").replace("https://openalex.org/", "").replace("https://doi.org/", "").lower() or None,
        authors=_authors(work.get("authorships")),
        year=_year(work),
        abstract=_abstract_from_inverted(work.get("abstract_inverted_index")),
        venue=src.get("display_name") or "",
        num_citations=int(work.get("cited_by_count") or 0),
        sources=[source_tag],
        openalex_id=(work.get("id") or "").replace("https://openalex.org/", "") or None,
        url=best_oa,
        pdf_url=pdf,
    )
    return p


class OpenAlexAdapter(CitationAdapter):
    name = "openalex"

    # ------------------------------------------------------------------
    def _work_url(self, doi: str) -> str:
        return f"{OPENALEX}/works/doi:{urllib.parse.quote(doi, safe='')}"

    def _mailto(self) -> str:
        return f"?mailto={urllib.parse.quote(config.mailto)}"

    # ------------------------------------------------------------------
    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        if doi:
            # cross-run DOI cache hit (instant, no network)
            from ..store import cache_get_paper, cache_put_paper
            cached = cache_get_paper(doi)
            if cached and cached.title:
                return cached
            url = self._work_url(doi) + self._mailto()
            status, data = rate_limiter.get_json(url)
            if status == 200 and data:
                p = _work_to_paper(data)
                if p and p.doi:
                    cache_put_paper(p)
                return p
        if title:
            # search by title
            url = f"{OPENALEX}/works"
            params = {
                "search": title,
                "per-page": 1,
                "select": WORK_SELECT,
                "mailto": config.mailto,
            }
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                results = data.get("results") or []
                if results:
                    return _work_to_paper(results[0])
        return None

    # ------------------------------------------------------------------
    def backward(self, paper: Paper) -> List[Paper]:
        """Return papers CITED BY `paper` (its references)."""
        if not paper.openalex_id and paper.doi:
            # hydrate to get the OpenAlex id + referenced_works
            p = self.resolve(paper.doi)
            if p:
                paper.merge(p)
        oa_id = paper.openalex_id
        if not oa_id:
            return []
        # referenced_works is a list of OpenAlex IDs (W...).  Batch-resolve
        # them 50 at a time, exactly like BackwardForwardSnowballing's
        # `openAlexResolveWorks`.
        ref_ids = []
        url = f"{OPENALEX}/works/{oa_id}" + self._mailto()
        # ask for the referenced_works array directly via select
        params = {"select": "id,referenced_works", "mailto": config.mailto}
        status, data = rate_limiter.get_json(url, params=params)
        if status != 200 or not data:
            return []
        ref_ids = data.get("referenced_works") or []
        if not ref_ids:
            return []
        ref_ids = [r.replace("https://openalex.org/", "") for r in ref_ids if r]
        # hydrate in batches of 50
        out: List[Paper] = []
        max_batches = config.max_resolve_batches
        for i in range(0, len(ref_ids), 50):
            if i // 50 >= max_batches:
                break
            batch = ref_ids[i : i + 50]
            flt = "|".join(batch)
            url = f"{OPENALEX}/works"
            params = {
                "filter": f"ids.openalex:{flt}",
                "per-page": 50,
                "select": WORK_SELECT,
                "mailto": config.mailto,
            }
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                for w in data.get("results") or []:
                    out.append(_work_to_paper(w))
            time.sleep(config.page_delay_ms / 1000.0)
        return out

    # ------------------------------------------------------------------
    def forward(self, paper: Paper) -> List[Paper]:
        """Return papers that CITE `paper` (cursor-paginated)."""
        if not paper.openalex_id and paper.doi:
            p = self.resolve(paper.doi)
            if p:
                paper.merge(p)
        oa_id = paper.openalex_id
        if not oa_id:
            return []
        out: List[Paper] = []
        cursor = "*"
        for _ in range(config.max_forward_pages_openalex):
            url = f"{OPENALEX}/works"
            params = {
                "filter": f"cites:{oa_id}",
                "per-page": 200,
                "cursor": cursor,
                "select": CITE_SELECT,
                "mailto": config.mailto,
            }
            status, data = rate_limiter.get_json(url, params=params)
            if status != 200 or not data:
                break
            results = data.get("results") or []
            if not results:
                break
            for w in results:
                out.append(_work_to_paper(w))
            cursor = (data.get("meta") or {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(config.page_delay_ms / 1000.0)
        return out

    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> List[Paper]:
        url = f"{OPENALEX}/works"
        params = {
            "search": query,
            "per-page": min(limit, 25),
            "select": WORK_SELECT,
            "mailto": config.mailto,
        }
        status, data = rate_limiter.get_json(url, params=params)
        if status != 200 or not data:
            return []
        out = []
        for w in data.get("results") or []:
            out.append(_work_to_paper(w))
        return out[:limit]

    # ------------------------------------------------------------------
    def hydrate_dois(self, dois: List[str]) -> List[Paper]:
        """Batch-resolve a list of DOIs into Papers (50 per call)."""
        out: List[Paper] = []
        dois = [d for d in dois if d]
        for i in range(0, len(dois), 50):
            if i // 50 >= config.max_resolve_batches:
                break
            batch = [d.lower() for d in dois[i : i + 50]]
            flt = "|".join(batch)
            url = f"{OPENALEX}/works"
            params = {
                "filter": f"doi:{flt}",
                "per-page": 50,
                "select": WORK_SELECT,
                "mailto": config.mailto,
            }
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                for w in data.get("results") or []:
                    out.append(_work_to_paper(w))
            time.sleep(config.page_delay_ms / 1000.0)
        return out

    def hydrate_abstracts(self, papers: List[Paper]) -> None:
        """Lazy-fill abstracts for papers that don't have one yet."""
        need = [p for p in papers if not p.abstract and p.doi]
        for p in self.hydrate_dois([p.doi for p in need]):
            for orig in need:
                if orig.doi and orig.doi == p.doi:
                    if p.abstract:
                        orig.abstract = p.abstract
                    break
