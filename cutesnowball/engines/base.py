"""Citation-graph adapter interface.

Each adapter knows how to:
  * resolve a seed identifier (DOI / title) into a Paper
  * fetch forward citations (papers that CITE the seed)
  * fetch backward references (papers CITED BY the seed)

Adapters normalise everything to the `Paper` model.  The snowball
orchestrator combines outputs from all enabled adapters and de-duplicates.

Adapters are intentionally simple, synchronous classes that share the
global `RateLimiter` instance.  The rate limiter guarantees per-host
politeness so enabling several adapters never causes a flood.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import Paper


class CitationAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        """Resolve a seed to a full Paper (title, authors, year, abstract, ids)."""

    @abstractmethod
    def forward(self, paper: Paper) -> List[Paper]:
        """Return papers that CITE `paper` (forward snowballing)."""

    @abstractmethod
    def backward(self, paper: Paper) -> List[Paper]:
        """Return papers CITED BY `paper` (backward snowballing)."""

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        """Keyword / title search.  Not all adapters support this."""
        return []

    def healthy(self) -> bool:
        """Cheap reachability probe.  Overridden where relevant."""
        return True
