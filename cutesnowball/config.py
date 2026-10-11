"""Central configuration for CuteySnowball.

All tunable knobs (delays, page caps, thresholds, enabled sources) live here
so the engine can be re-tuned without touching the snowballing core.  This
mirrors the `SNOWBALL_CONFIG` pattern from the upstream
BackwardForwardSnowballing project (abequet/BackwardForwardSnowballing).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, List


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- Identity / politeness ----------------------------------------------
    # Crossref/OpenAlex "polite pool" address.  Must be a real mailbox you
    # monitor so the API staff can contact you if needed.
    mailto: str = os.environ.get("CUTESNOWBALL_MAILTO", "cuteysnowball@example.org")

    # Host to bind the Flask dev server to.
    host: str = os.environ.get("CUTESNOWBALL_HOST", "0.0.0.0")
    port: int = int(os.environ.get("CUTESNOWBALL_PORT", "5000"))

    # SQLite database path (run persistence).
    db_path: str = os.environ.get(
        "CUTESNOWBALL_DB", os.path.join(os.path.expanduser("~"), ".cuteysnowball", "runs.sqlite")
    )

    # --- Source toggles ------------------------------------------------------
    # Free, no-key, no-blocking academic APIs (PRIMARY - always safe).
    enable_openalex: bool = _env_bool("CUTESNOWBALL_ENABLE_OPENALEX", True)
    enable_semantic_scholar: bool = _env_bool("CUTESNOWBALL_ENABLE_S2", True)
    enable_crossref: bool = _env_bool("CUTESNOWBALL_ENABLE_CROSSREF", True)
    enable_opencitations: bool = _env_bool("CUTESNOWBALL_ENABLE_OPENCITATIONS", True)

    # Google Scholar enrichment (SECONDARY - blocking risk, opt-in).
    enable_scholarly: bool = _env_bool("CUTESNOWBALL_ENABLE_SCHOLARLY", False)
    enable_scholar_scrape: bool = _env_bool("CUTESNOWBALL_ENABLE_SCHOLAR_SCRAPE", False)

    # Scholarly proxy mode: "free", "scraperapi", "none"
    scholar_proxy_mode: str = os.environ.get("CUTESNOWBALL_SCHOLAR_PROXY", "free")
    scholar_scraperapi_key: str = os.environ.get("CUTESNOWBALL_SCRAPERAPI_KEY", "")

    # --- Rate limiting (per host) -------------------------------------------
    # Minimum delay between requests to the same host (seconds).
    min_delay_per_host: float = float(os.environ.get("CUTESNOWBALL_MIN_DELAY", "0.6"))
    # Jitter added to every delay so requests look human (seconds).
    jitter: float = float(os.environ.get("CUTESNOWBALL_JITTER", "0.5"))
    # Backoff multiplier on HTTP 429 (seconds added before retry).
    backoff_429: float = float(os.environ.get("CUTESNOWBALL_BACKOFF_429", "5.0"))
    # Max retries per request before giving up.
    max_retries: int = int(os.environ.get("CUTESNOWBALL_MAX_RETRIES", "3"))
    # Per-request timeout (seconds).
    request_timeout: float = float(os.environ.get("CUTESNOWBALL_TIMEOUT", "20.0"))

    # --- Snowballing safety caps (mirrors upstream SNOWBALL_CONFIG) ---------
    max_forward_pages_openalex: int = 30     # * 200 results = 6 000 citing works
    max_s2_pages: int = 10                   # * 1000 results = 10 000 items
    max_resolve_batches: int = 20            # OpenAlex DOI-hydration batches * 50
    page_delay_ms: int = 250                  # polite pause between paged requests
    enrich_batch_size: int = 3                # Crossref DOI resolution concurrency
    enrich_batch_delay_ms: int = 800          # gap between batches

    # --- Snowballing loop ---------------------------------------------------
    max_iterations: int = 5                  # Wohlin-style safety cap
    max_total_papers: int = 500              # hard corpus cap
    min_relevance: float = 0.18              # below this a candidate is dropped
    per_round_cap: int = 60                  # if a round yields more, keep top-N by score
    saturation_threshold: int = 1            # <= N new eligible papers => saturated

    # --- Relevancy weighting ------------------------------------------------
    w_tfidf: float = 0.45
    w_keyword: float = 0.25
    w_recency: float = 0.15
    w_citations: float = 0.15
    recency_ref_year: int = 2000
    recency_tau: float = 10.0  # exp(-(year-ref)/tau)

    # --- Misc ----------------------------------------------------------------
    secret_key: str = os.environ.get("CUTESNOWBALL_SECRET", str(uuid.uuid4()))
    debug: bool = _env_bool("CUTESNOWBALL_DEBUG", False)

    def source_weights(self) -> Dict[str, float]:
        """Return the relevancy weights as a dict (used by relevance.py)."""
        return {
            "tfidf": self.w_tfidf,
            "keyword": self.w_keyword,
            "recency": self.w_recency,
            "citations": self.w_citations,
        }


# Singleton used everywhere.
config = Config()


def seed_sources() -> List[str]:
    """Names of citation-graph sources enabled in the current config."""
    out = []
    if config.enable_openalex:
        out.append("openalex")
    if config.enable_semantic_scholar:
        out.append("semantic_scholar")
    if config.enable_crossref:
        out.append("crossref")
    if config.enable_opencitations:
        out.append("opencitations")
    if config.enable_scholarly:
        out.append("scholarly")
    if config.enable_scholar_scrape:
        out.append("scholar_scrape")
    return out
