"""scholarly adapter (optional) — Google Scholar via the `scholarly` package.

This is a SECONDARY enrichment source.  It is OFF by default because Google
Scholar aggressively blocks IPs that issue many `search_pubs`/`citedby`
queries.  Enable it via `CUTESNOWBALL_ENABLE_SCHOLARLY=1` and supply a
proxy (free or ScraperAPI) to reduce ban risk.

`scholarly` supports forward snowballing (cited-by) but NOT backward
(references) — for backward we rely on Crossref / OpenAlex / S2.

Anti-block config (per the scholarly docs and the project's own README):
  * FreeProxies(timeout=1.5, wait_time=180) - rotate free proxies
  * scholarly.use_proxy(pg, pg) - route EVERYTHING through proxies,
    never the local IP
  * scholarly.set_timeout(15); set_retries(5)
  * On MaxTriesExceededException -> pause >=1h.  On DOSException -> pause >=24h.
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from ..config import config
from ..models import Paper
from .base import CitationAdapter

log = logging.getLogger("cutesnowball.scholarly")

try:
    from scholarly import scholarly, ProxyGenerator  # type: ignore
    from scholarly._proxy_generator import (  # type: ignore
        MaxTriesExceededException,
        DOSException,
    )

    _SCHOLARLY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dep
    _SCHOLARLY_AVAILABLE = False
    MaxTriesExceededException = Exception
    DOSException = Exception


def _init_scholarly() -> bool:
    if not _SCHOLARLY_AVAILABLE:
        return False
    if config.scholar_proxy_mode == "none":
        return True
    try:
        pg = ProxyGenerator()
        if config.scholar_proxy_mode == "scraperapi" and config.scholar_scraperapi_key:
            pg.ScraperAPI(config.scholar_scraperapi_key)
            scholarly.use_proxy(pg)
            scholarly.set_timeout(60)
        else:
            pg.FreeProxies(timeout=1.5, wait_time=180)
            # route EVERYTHING through proxies to protect the local IP
            scholarly.use_proxy(pg, pg)
            scholarly.set_timeout(15)
        scholarly.set_retries(5)
        scholarly.set_logger(False)
        return True
    except Exception as exc:  # pragma: no cover
        log.warning("scholarly proxy init failed: %s", exc)
        return False


_INITIALIZED = False


def _ensure_init() -> bool:
    global _INITIALIZED
    if _INITIALIZED:
        return True
    _INITIALIZED = _init_scholarly()
    return _INITIALIZED


def _pub_to_paper(pub) -> Paper:
    bib = pub.get("bib") or {}
    ext = {}
    authors = bib.get("author") or ""
    if isinstance(authors, list):
        authors = "; ".join(str(a) for a in authors)
    return Paper(
        title=bib.get("title") or "",
        doi=ext.get("DOI"),
        authors=authors,
        year=_int(bib.get("pub_year")),
        abstract=bib.get("abstract") or "",
        venue=bib.get("venue") or "",
        num_citations=int(pub.get("num_citations") or 0),
        sources=["scholarly"],
        scholar_id=pub.get("author_pub_id"),
        url=pub.get("pub_url") or "",
        pdf_url=pub.get("eprint_url") or "",
    )


def _int(v):
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


class ScholarlyAdapter(CitationAdapter):
    name = "scholarly"

    def healthy(self) -> bool:
        return _SCHOLARLY_AVAILABLE and _ensure_init()

    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        if not _ensure_init():
            return None
        q = title or doi
        if not q:
            return None
        try:
            res = scholarly.search_pubs(q)
            pub = next(res, None)
            if pub:
                return _pub_to_paper(pub)
        except (MaxTriesExceededException, DOSException) as exc:
            log.warning("scholarly blocked: %s", exc)
            raise
        except StopIteration:
            return None
        except Exception as exc:
            log.warning("scholarly resolve failed: %s", exc)
        return None

    def forward(self, paper: Paper) -> List[Paper]:
        if not _ensure_init():
            return []
        # need a filled publication with citedby_url; search by title is most robust
        try:
            q = paper.title or paper.doi
            if not q:
                return []
            res = scholarly.search_pubs(q)
            pub = next(res, None)
            if not pub:
                return []
            pub = scholarly.fill(pub)
            cited = scholarly.citedby(pub)
            out = []
            for c in cited:
                out.append(_pub_to_paper(c))
            return out
        except (MaxTriesExceededException, DOSException) as exc:
            log.warning("scholarly forward blocked: %s", exc)
            raise
        except Exception as exc:
            log.warning("scholarly forward failed: %s", exc)
            return []

    def backward(self, paper: Paper) -> List[Paper]:
        # scholarly does NOT support backward snowballing
        return []

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        if not _ensure_init():
            return []
        try:
            res = scholarly.search_pubs(query)
            out = []
            for i, pub in enumerate(res):
                if i >= limit:
                    break
                out.append(_pub_to_paper(pub))
            return out
        except (MaxTriesExceededException, DOSException) as exc:
            log.warning("scholarly search blocked: %s", exc)
            return []
        except Exception as exc:
            log.warning("scholarly search failed: %s", exc)
            return []
