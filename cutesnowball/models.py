"""Data models for CuteySnowball.

A `Paper` is the universal record that every citation-graph adapter normalises
to (mirrors the unified ref shape from the BackwardForwardSnowballing project).
A `Run` holds the live state of a snowballing session.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set


def _norm_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    d = d.rstrip(".,;)]}")
    return d or None


@dataclass
class Paper:
    """A normalised academic paper record."""
    title: str = ""
    doi: Optional[str] = None          # normalised lowercase, no resolver prefix
    authors: str = ""                 # "Family, Given; Family, Given"
    year: Optional[int] = None
    abstract: str = ""
    venue: str = ""
    num_citations: int = 0            # citation count (citation index only)
    sources: List[str] = field(default_factory=list)  # ["openalex","crossref",...]
    seed: bool = False                 # True for user-supplied seed papers
    # --- snowballing bookkeeping ---
    depth: int = 0                    # hop distance from nearest seed
    discovered_round: int = 0         # which snowball iteration found it
    relevance: float = 0.0           # 0..1 score vs the seed set
    included: bool = True              # survived the relevance filter
    excluded_reason: str = ""
    scholar_id: Optional[str] = None  # Semantic Scholar / OpenAlex id
    openalex_id: Optional[str] = None
    url: str = ""
    pdf_url: str = ""
    raw: str = ""                     # raw ref string (PDF parse only)

    # --- identity ---
    def key(self) -> str:
        """Stable identity key: DOI if present, else lowercased title hash."""
        if self.doi:
            return f"doi:{self.doi}"
        base = (self.title or "").strip().lower()
        if not base:
            return "id:empty"
        h = hashlib.md5(base.encode("utf-8")).hexdigest()[:12]
        return f"t:{h}"

    def merge(self, other: "Paper") -> "Paper":
        """Merge another Paper into self, keeping the richer field."""
        if not self.title and other.title:
            self.title = other.title
        if not self.doi and other.doi:
            self.doi = other.doi
        if len(other.authors) > len(self.authors):
            self.authors = other.authors
        if self.year is None and other.year:
            self.year = other.year
        if len(other.abstract) > len(self.abstract):
            self.abstract = other.abstract
        if not self.venue and other.venue:
            self.venue = other.venue
        if other.num_citations > self.num_citations:
            self.num_citations = other.num_citations
        if not self.openalex_id and other.openalex_id:
            self.openalex_id = other.openalex_id
        if not self.scholar_id and other.scholar_id:
            self.scholar_id = other.scholar_id
        if not self.pdf_url and other.pdf_url:
            self.pdf_url = other.pdf_url
        if not self.url and other.url:
            self.url = other.url
        for s in other.sources:
            if s not in self.sources:
                self.sources.append(s)
        # keep the *smaller* depth (closer to a seed) and *earlier* round
        if other.depth < self.depth:
            self.depth = other.depth
        if other.discovered_round and (
            not self.discovered_round or other.discovered_round < self.discovered_round
        ):
            self.discovered_round = other.discovered_round
        # relevance: keep the max
        if other.relevance > self.relevance:
            self.relevance = other.relevance
        return self

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["key"] = self.key()
        return d

    @staticmethod
    def from_dict(d: Dict) -> "Paper":
        p = Paper()
        p.title = d.get("title", "") or ""
        p.doi = _norm_doi(d.get("doi"))
        p.authors = d.get("authors", "") or ""
        y = d.get("year")
        try:
            p.year = int(y) if y not in (None, "", 0) else None
        except (TypeError, ValueError):
            p.year = None
        p.abstract = d.get("abstract", "") or ""
        p.venue = d.get("venue", "") or ""
        p.num_citations = int(d.get("num_citations", 0) or 0)
        p.sources = list(d.get("sources", []) or [])
        p.openalex_id = d.get("openalex_id") or None
        p.scholar_id = d.get("scholar_id") or None
        p.url = d.get("url", "") or ""
        p.pdf_url = d.get("pdf_url", "") or ""
        p.raw = d.get("raw", "") or ""
        return p


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

# PRISMA 2020 four-phase flow.
PHASES = ("identification", "screening", "eligibility", "included")


@dataclass
class Run:
    """A single snowballing run."""
    run_id: str
    mode: str                          # "paper" or "keyword"
    seeds_input: List[str] = field(default_factory=list)  # raw user inputs
    keywords: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    status: str = "pending"            # pending/running/done/error/paused
    phase: str = "identification"
    message: str = ""
    tags: List[str] = field(default_factory=list)  # user-assigned labels
    # papers keyed by Paper.key()
    papers: Dict[str, Paper] = field(default_factory=dict)
    # edges: list of (source_key -> citing_key, direction)  direction in {forward,backward}
    edges: List[Dict] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)
    options: Dict = field(default_factory=dict)
    error: str = ""

    def add_paper(self, p: Paper) -> Paper:
        k = p.key()
        if k in self.papers:
            self.papers[k] = self.papers[k].merge(p)
        else:
            self.papers[k] = p
        return self.papers[k]

    def has(self, p: Paper) -> bool:
        return p.key() in self.papers

    def add_edge(self, src_key: str, dst_key: str, direction: str):
        # dedup
        for e in self.edges:
            if e["source"] == src_key and e["target"] == dst_key and e["direction"] == direction:
                return
        self.edges.append({"source": src_key, "target": dst_key, "direction": direction})

    def to_dict(self, include_abstracts: bool = True) -> Dict:
        papers = []
        for p in self.papers.values():
            d = p.to_dict()
            if not include_abstracts:
                d.pop("abstract", None)
            papers.append(d)
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "seeds_input": self.seeds_input,
            "keywords": self.keywords,
            "status": self.status,
            "phase": self.phase,
            "message": self.message,
            "tags": self.tags,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "paper_count": len(self.papers),
            "edge_count": len(self.edges),
            "papers": papers,
            "edges": self.edges,
            "stats": self.stats,
            "options": self.options,
            "error": self.error,
        }

    def stats_snapshot(self) -> Dict:
        seeds = sum(1 for p in self.papers.values() if p.seed)
        included = sum(1 for p in self.papers.values() if p.included)
        excluded = len(self.papers) - included
        forward_edges = sum(1 for e in self.edges if e["direction"] == "forward")
        backward_edges = sum(1 for e in self.edges if e["direction"] == "backward")
        years = [p.year for p in self.papers.values() if p.year]
        return {
            "total_papers": len(self.papers),
            "seeds": seeds,
            "included": included,
            "excluded": excluded,
            "forward_edges": forward_edges,
            "backward_edges": backward_edges,
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "phase": self.phase,
            "status": self.status,
        }


def new_run_id() -> str:
    import uuid as _u
    return _u.uuid4().hex[:12]
