"""OpenCitations adapter — free, open citation data, DOI-only rows.

OpenCitations (https://opencitations.net) provides fully open citation
metadata.  Its COCI index returns rows with `citing` and `cited` DOI strings
only (no titles).  We therefore always pair this adapter with OpenAlex's
`hydrate_dois()` for title resolution — exactly as the upstream
BackwardForwardSnowballing project does.

Endpoints:
  citations  -> list of DOIs that CITE the seed  (forward)
  references -> list of DOIs CITED BY the seed   (backward)
"""
from __future__ import annotations

from typing import List, Optional

from ..config import config
from ..models import Paper
from ..rate_limiter import rate_limiter
from .base import CitationAdapter

OC = "https://api.opencitations.net/index/v2"

_DOI_RE = None  # placeholder


def _extract_dois(rows, field: str) -> List[str]:
    """From OC rows, pull the DOI on `field` and normalise."""
    import re

    out = []
    for row in rows or []:
        v = row.get(field) or ""
        if not v:
            continue
        v = v.strip().lower()
        if v.startswith("doi:"):
            v = v[4:]
        v = v.replace("https://doi.org/", "").rstrip(".,;)]}")
        if v:
            out.append(v)
    return out


class OpenCitationsAdapter(CitationAdapter):
    name = "opencitations"

    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        # OpenCitations has no metadata endpoint - just citation links.
        # Return a stub so the orchestrator can still walk citations.
        if not doi:
            return None
        return Paper(doi=doi.lower(), title="", sources=["opencitations"])

    def forward(self, paper: Paper) -> List[Paper]:
        if not paper.doi:
            return []
        url = f"{OC}/citations/doi:{paper.doi}"
        status, data = rate_limiter.get_json(url)
        if status != 200 or not isinstance(data, list):
            return []
        dois = _extract_dois(data, "citing")
        # remove self
        dois = [d for d in dois if d != paper.doi]
        return [Paper(doi=d, title="", sources=["opencitations"]) for d in dois]

    def backward(self, paper: Paper) -> List[Paper]:
        if not paper.doi:
            return []
        url = f"{OC}/references/doi:{paper.doi}"
        status, data = rate_limiter.get_json(url)
        if status != 200 or not isinstance(data, list):
            return []
        dois = _extract_dois(data, "cited")
        dois = [d for d in dois if d != paper.doi]
        return [Paper(doi=d, title="", sources=["opencitations"]) for d in dois]
