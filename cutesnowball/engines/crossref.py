"""Crossref adapter — free, polite pool via `mailto`.

Crossref is the canonical source for the `reference[]` array of a work
(i.e. backward snowballing) because publishers deposit their bibliographies
there.  It also exposes a bibliographic search endpoint we use for keyword
seed discovery.

Mirrors BackwardForwardSnowballing's `fetchFromAPIs` Crossref branch and
`resolveOneDOI` retry-on-429 behaviour.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

from ..config import config
from ..models import Paper
from ..rate_limiter import rate_limiter
from .base import CitationAdapter

CROSSREF = "https://api.crossref.org"

# Vancouver / APA-ish unstructured-citation parser (ported from
# BackwardForwardSnowballing's parseUnstructuredRef in api.js).
_YEAR_RE = re.compile(r"\((\d{4})\)|(?<=[\s,;])(\d{4})(?=[;:,.\s]|$)")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;}\]\)]+)", re.IGNORECASE)


def _authors_from_crossref(authors) -> str:
    out = []
    for a in authors or []:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        if family:
            out.append(f"{family}, {given}" if given else family)
    return "; ".join(out)[:300]


def _crossref_to_paper(work: dict) -> Paper:
    msg = work.get("message") if "message" in work else work
    title = ""
    if msg.get("title"):
        title = msg["title"][0] if isinstance(msg["title"], list) else msg["title"]
    doi = (msg.get("DOI") or "").lower() or None
    authors = _authors_from_crossref(msg.get("author"))
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        d = msg.get(key, {})
        if d and d.get("date-parts"):
            try:
                year = int(d["date-parts"][0][0])
                break
            except (IndexError, ValueError, TypeError):
                continue
    abstract = msg.get("abstract") or ""
    # strip JSTOR/JATS XML tags from abstract
    if abstract:
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()
    venue = ""
    if msg.get("container-title"):
        venue = (
            msg["container-title"][0]
            if isinstance(msg["container-title"], list)
            else msg["container-title"]
        )
    url = msg.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    return Paper(
        title=title or "",
        doi=doi,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        num_citations=int(msg.get("is-referenced-by-count") or 0),
        sources=["crossref"],
        url=url,
    )


# Patterns for access-metadata noise we want to strip from unstructured titles.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_ACCESS_RE = re.compile(
    r"\s*[\[\(]?(?:Accessed|Retrieved|Available from|Cited|Viewed|Visited)"
    r"[^\]]{0,60}?\]?\s*\.?\s*$",
    re.IGNORECASE,
)
_BRACKET_CITE_RE = re.compile(r"\s*\[(?:cited|viewed)\s[^\]]*\]\s*\.?\s*$", re.IGNORECASE)


def _clean_unstructured_title(text: str) -> str:
    """Strip URLs, access-date metadata, and trailing junk from a citation fragment."""
    # remove URLs
    text = _URL_RE.sub("", text)
    # remove "Accessed: DATE" / "Retrieved from ..." tails
    text = _ACCESS_RE.sub("", text)
    text = _BRACKET_CITE_RE.sub("", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # strip leading/trailing punctuation
    text = text.strip(" .,;:\"'[](){}")
    return text


def _parse_unstructured_ref(raw: str) -> Optional[Paper]:
    """Parse an unstructured citation string into a best-effort Paper.

    Handles the messy real-world citation strings Crossref deposits, e.g.:
      "GitHub: http://github.com. Accessed: 2013-08-21. [cited 2024-01-15]"
      "Smith J. Some title. Nature 2020;576:120-125. doi:10.1038/..."
    Strips URLs and access metadata so the title is human-readable.
    """
    if not raw or len(raw) < 25:
        return None
    raw = raw.strip()
    doi_m = _DOI_RE.search(raw)
    doi = doi_m.group(1).lower().rstrip(".,;)]}") if doi_m else None
    year_m = _YEAR_RE.search(raw[:160])
    year = None
    year_end = None
    if year_m:
        for g in year_m.groups():
            if g:
                try:
                    year = int(g)
                    year_end = year_m.end()
                    break
                except ValueError:
                    continue
    # title = text before the year (if any), else the whole raw string
    title_src = raw[: year_m.start()] if year_m else raw
    title = _clean_unstructured_title(title_src)
    # if the cleaned title is too short (e.g. URL-only ref), try the part after the year
    if len(title) < 12 and year_m:
        title = _clean_unstructured_title(raw[year_end:])
    # last resort: if still too short, mark as untitled (so it can be filtered later)
    if len(title) < 8:
        title = ""
    return Paper(
        title=title,
        doi=doi,
        authors="",
        year=year,
        abstract="",
        sources=["crossref"],
        raw=raw,
    )


class CrossrefAdapter(CitationAdapter):
    name = "crossref"

    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        if doi:
            url = f"{CROSSREF}/works/{doi}"
            params = {"mailto": config.mailto}
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                return _crossref_to_paper(data)
        if title:
            url = f"{CROSSREF}/works"
            params = {
                "query.bibliographic": title,
                "rows": 1,
                "select": "DOI,title,author,published-print,published-online,issued,abstract,is-referenced-by-count,URL,container-title",
                "mailto": config.mailto,
            }
            status, data = rate_limiter.get_json(url, params=params)
            if status == 200 and data:
                items = (data.get("message") or {}).get("items") or []
                if items:
                    return _crossref_to_paper(items[0])
        return None

    def backward(self, paper: Paper) -> List[Paper]:
        """Crossref's `reference[]` array is the paper's bibliography."""
        if not paper.doi:
            return []
        url = f"{CROSSREF}/works/{paper.doi}"
        params = {"mailto": config.mailto}
        status, data = rate_limiter.get_json(url, params=params)
        if status != 200 or not data:
            return []
        msg = (data.get("message") or {}).get("message", data.get("message"))
        if not msg:
            msg = data.get("message", {})
        refs = msg.get("reference") or []
        out: List[Paper] = []
        for r in refs:
            # structured ref
            if r.get("DOI") or r.get("article-title") or r.get("title"):
                doi = (r.get("DOI") or "").lower() or None
                if doi:
                    doi = doi.rstrip(".,;)]}")
                title = r.get("article-title") or r.get("title") or ""
                authors = _authors_from_crossref(
                    [{"given": r.get("given", ""), "family": r.get("author", "")}]
                )
                year = None
                try:
                    year = int(r.get("year")) if r.get("year") else None
                except (TypeError, ValueError):
                    year = None
                out.append(
                    Paper(
                        title=title,
                        doi=doi,
                        authors=authors,
                        year=year,
                        sources=["crossref"],
                        raw=r.get("unstructured") or "",
                    )
                )
            elif r.get("unstructured"):
                p = _parse_unstructured_ref(r["unstructured"])
                if p:
                    out.append(p)
        return out

    def forward(self, paper: Paper) -> List[Paper]:
        """Crossref has no public forward-citation list endpoint that is free.
        We return [] so the orchestrator falls back to OpenAlex / S2 / OC.
        """
        return []

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        url = f"{CROSSREF}/works"
        params = {
            "query.bibliographic": query,
            "rows": min(limit, 25),
            "select": "DOI,title,author,published-print,published-online,issued,abstract,is-referenced-by-count,URL,container-title",
            "mailto": config.mailto,
        }
        status, data = rate_limiter.get_json(url, params=params)
        if status != 200 or not data:
            return []
        items = (data.get("message") or {}).get("items") or []
        return [_crossref_to_paper(it) for it in items][:limit]
