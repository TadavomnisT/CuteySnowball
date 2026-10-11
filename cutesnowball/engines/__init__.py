"""Engine adapters package."""
from .base import CitationAdapter
from .openalex import OpenAlexAdapter
from .semanticscholar import SemanticScholarAdapter
from .crossref import CrossrefAdapter
from .opencitations import OpenCitationsAdapter

# Optional Google Scholar enrichment adapters (lazy-imported on demand).
__all__ = [
    "CitationAdapter",
    "OpenAlexAdapter",
    "SemanticScholarAdapter",
    "CrossrefAdapter",
    "OpenCitationsAdapter",
]


def build_adapters(cfg) -> list:
    """Instantiate the set of adapters enabled in the config."""
    out = []
    if cfg.enable_openalex:
        out.append(OpenAlexAdapter())
    if cfg.enable_semantic_scholar:
        out.append(SemanticScholarAdapter())
    if cfg.enable_crossref:
        out.append(CrossrefAdapter())
    if cfg.enable_opencitations:
        out.append(OpenCitationsAdapter())
    if cfg.enable_scholarly:
        try:
            from .scholar_scholarly import ScholarlyAdapter

            out.append(ScholarlyAdapter())
        except Exception:
            pass
    if cfg.enable_scholar_scrape:
        try:
            from .scholar_scrape import ScholarScrapeAdapter

            out.append(ScholarScrapeAdapter())
        except Exception:
            pass
    return out
