"""Snowballing orchestrator.

Implements the bi-directional Snowballing-by-Study (SBS) algorithm from
Wohlin (2014), generalised to a queue-based BFS so it can run unattended:

  1. Build the SEED set (option 1: user-supplied DOIs/PDFs;
     option 2: keyword search -> top-N most-relevant results).
  2. Score every seed with the RelevanceScorer (seeds score 1.0).
  3. For each paper in the queue, in round r=1..max_iterations:
       a) Backward: ask every adapter for the paper's references.
       b) Forward:  ask every adapter for the paper's citations.
       c) Merge new papers into the corpus (Paper.merge keeps richer fields).
       d) Add citation edges (source -> target, direction).
       e) Score new papers; drop those below `min_relevance`.
       f) If a round yielded more than `per_round_cap` candidates, keep the
          top-N by score (this is the "filter and go on with relevant papers"
          requirement from the spec).
       g) Stopping: saturation (<= saturation_threshold new eligible) OR
          max_iterations OR max_total_papers.
  4. Lazy-fill abstracts from OpenAlex for any paper still missing one.
  5. Mark the run done.

The orchestrator streams progress events to the caller via a callback so
the Flask SSE route can push them to the browser in real time.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Callable, Dict, List, Optional

from .config import config
from .engines import build_adapters
from .models import Paper, Run, new_run_id, PHASES
from .rate_limiter import rate_limiter
from .relevance import RelevanceScorer
from .store import save_run, new_run as store_new_run

log = logging.getLogger("cutesnowball.snowball")

# An event callback: (event:dict) -> None
EventCb = Callable[[dict], None]


def _emit(cb: Optional[EventCb], **kw):
    if cb is None:
        return
    try:
        cb({"ts": time.time(), **kw})
    except Exception:
        pass


class Snowballer:
    """Runs a forward+backward snowballing session."""

    def __init__(self, run: Run, event_cb: Optional[EventCb] = None):
        self.run = run
        self.cb = event_cb
        self.adapters = build_adapters(config)
        self.stop_flag = threading.Event()
        self._scorer: Optional[RelevanceScorer] = None

    # ------------------------------------------------------------------
    def stop(self):
        self.stop_flag.set()

    # ------------------------------------------------------------------
    def _resolve_seed(self, raw: str, is_pdf: bool = False, pdf_data: bytes = b"") -> Optional[Paper]:
        """Resolve a user input (DOI, title, or PDF bytes) into a Paper."""
        raw = (raw or "").strip()
        if not raw and not is_pdf:
            return None
        # PDF path: extract DOI + references from the PDF
        if is_pdf and pdf_data:
            from .pdf_parser import extract_references_from_pdf

            doi, refs = extract_references_from_pdf(pdf_data)
            # The seed paper itself is the PDF; we don't have its metadata
            # unless we can resolve its DOI via OpenAlex/Crossref.
            seed = Paper(title="(PDF seed)", doi=doi, sources=["pdf"], seed=True)
            if doi:
                for ad in self.adapters:
                    try:
                        p = ad.resolve(doi)
                        if p and p.title and p.title != "(PDF seed)":
                            seed.merge(p)
                            break
                    except Exception:
                        continue
            # Also add the PDF's references as backward children
            for r in refs:
                r.discovered_round = 0
                self.run.add_paper(r)
                if seed.doi or seed.title:
                    self.run.add_edge(seed.key(), r.key(), "backward")
            return seed

        # DOI path
        if raw.lower().startswith("10.") or "doi.org/" in raw.lower():
            doi = raw.lower()
            if "doi.org/" in doi:
                doi = doi.split("doi.org/", 1)[1]
            doi = doi.rstrip(".,;)]}")
            for ad in self.adapters:
                try:
                    p = ad.resolve(doi)
                    if p and p.title:
                        return p
                except Exception as exc:
                    log.warning("seed resolve %s via %s failed: %s", doi, ad.name, exc)
                    continue
            # fallback: stub
            return Paper(doi=doi, title="", sources=[], seed=True)

        # Title path
        for ad in self.adapters:
            try:
                p = ad.resolve(None, title=raw)
                if p and p.title:
                    return p
            except Exception as exc:
                log.warning("seed resolve title via %s failed: %s", ad.name, exc)
                continue
        # last resort: a bare title seed
        return Paper(title=raw, sources=[], seed=True)

    # ------------------------------------------------------------------
    def _keyword_seeds(self, keywords: List[str], top_n: int = 8) -> List[Paper]:
        """Option 2: search every adapter for the keywords, merge, score,
        keep the top-N as seeds."""
        query = " ".join(keywords).strip()
        if not query:
            return []
        _emit(self.cb, phase="identification", msg=f"Searching for '{query}'…")
        candidates: Dict[str, Paper] = {}
        for ad in self.adapters:
            try:
                results = ad.search(query, limit=15)
                for r in results:
                    if not r.title and not r.doi:
                        continue
                    k = r.key()
                    if k in candidates:
                        candidates[k] = candidates[k].merge(r)
                    else:
                        candidates[k] = r
            except Exception as exc:
                log.warning("search via %s failed: %s", ad.name, exc)
                _emit(self.cb, phase="identification", msg=f"{ad.name} search error: {exc}")
                continue
        if not candidates:
            return []
        # quick relevance pre-score using just the keywords as the seed text
        kw_paper = Paper(title=query, abstract="", sources=[])
        scorer = RelevanceScorer([kw_paper])
        scored = list(candidates.values())
        for p in scored:
            p.relevance = scorer.score(p)
        scored.sort(key=lambda p: p.relevance, reverse=True)
        seeds = scored[:top_n]
        for s in seeds:
            s.seed = True
            s.relevance = max(s.relevance, 0.7)  # seeds are inherently relevant
        return seeds

    # ------------------------------------------------------------------
    def _walk_paper(self, paper: Paper, round_idx: int) -> List[Paper]:
        """Run forward + backward snowball on a single paper.

        Returns the list of NEW papers discovered (already merged into run).
        """
        new_papers: List[Paper] = []
        # --- backward (references) ---
        for ad in self.adapters:
            if self.stop_flag.is_set():
                break
            try:
                refs = ad.backward(paper)
            except Exception as exc:
                log.warning("%s.backward failed: %s", ad.name, exc)
                _emit(
                    self.cb,
                    phase="eligibility",
                    msg=f"{ad.name} backward error on '{paper.title[:40]}': {exc}",
                )
                continue
            for r in refs or []:
                if not r.title and not r.doi:
                    continue
                already = self.run.has(r)
                merged = self.run.add_paper(r)
                merged.discovered_round = merged.discovered_round or round_idx
                self.run.add_edge(paper.key(), merged.key(), "backward")
                if not already and merged is r:
                    new_papers.append(merged)
                elif not already:
                    new_papers.append(merged)
            _emit(
                self.cb,
                phase="eligibility",
                msg=f"{ad.name}: {len(refs or [])} references from '{paper.title[:40]}…'",
            )
        # --- forward (citations) ---
        for ad in self.adapters:
            if self.stop_flag.is_set():
                break
            try:
                cites = ad.forward(paper)
            except Exception as exc:
                log.warning("%s.forward failed: %s", ad.name, exc)
                _emit(
                    self.cb,
                    phase="eligibility",
                    msg=f"{ad.name} forward error on '{paper.title[:40]}': {exc}",
                )
                continue
            for c in cites or []:
                if not c.title and not c.doi:
                    continue
                already = self.run.has(c)
                merged = self.run.add_paper(c)
                merged.discovered_round = merged.discovered_round or round_idx
                self.run.add_edge(merged.key(), paper.key(), "forward")
                if not already:
                    new_papers.append(merged)
            _emit(
                self.cb,
                phase="eligibility",
                msg=f"{ad.name}: {len(cites or [])} citations of '{paper.title[:40]}…'",
            )
        return new_papers

    # ------------------------------------------------------------------
    def _hydrate_titles(self):
        """For DOI-only stubs (OpenCitations gives DOI, no title), hydrate
        titles + abstracts from OpenAlex in batches of 50."""
        from .engines.openalex import OpenAlexAdapter

        oa = next((a for a in self.adapters if a.name == "openalex"), None)
        if not oa:
            return
        need = [p for p in self.run.papers.values() if not p.title and p.doi]
        if not need:
            return
        _emit(self.cb, phase="screening", msg=f"Hydrating titles for {len(need)} papers…")
        hydrated = oa.hydrate_dois([p.doi for p in need if p.doi])
        by_doi = {p.doi: p for p in hydrated if p.doi}
        for orig in need:
            h = by_doi.get(orig.doi)
            if h:
                orig.merge(h)

    # ------------------------------------------------------------------
    def run_snowball(self):
        """Top-level entry.  Picks mode from self.run.mode."""
        self.run.status = "running"
        self.run.started_at = time.time()
        save_run(self.run)
        try:
            if self.run.mode == "keyword":
                self._do_keyword_mode()
            else:
                self._do_paper_mode()
            self.run.status = "done"
            self.run.phase = "included"
            self.run.stats = self.run.stats_snapshot()
            _emit(self.cb, phase="included", msg="Snowballing complete.", stats=self.run.stats_snapshot())
        except Exception as exc:
            self.run.status = "error"
            self.run.error = str(exc)
            log.error("snowball failed: %s\n%s", exc, traceback.format_exc())
            _emit(self.cb, phase="error", msg=f"Error: {exc}")
        finally:
            self.run.finished_at = time.time()
            save_run(self.run)

    # ------------------------------------------------------------------
    def resume(self):
        """Resume a stopped/errored run by walking papers not yet expanded.

        A paper is considered 'not yet expanded' if it has no outgoing edges
        in the run's edge list.  We re-fit the scorer on existing seeds and
        re-run the BFS queue from those un-walked papers.
        """
        self.run.status = "running"
        self.run.error = ""
        save_run(self.run)
        try:
            seeds = [p for p in self.run.papers.values() if p.seed]
            if not seeds:
                _emit(self.cb, phase="error", msg="No seeds in run; cannot resume.")
                self.run.status = "error"
                self.run.error = "no seeds"
                return
            # re-fit scorer (with optional weights)
            weights = None
            if isinstance(self.run.options, dict) and self.run.options.get("weights"):
                w = self.run.options["weights"]
                weights = {
                    "tfidf": float(w.get("tfidf", config.w_tfidf)),
                    "keyword": float(w.get("keyword", config.w_keyword)),
                    "recency": float(w.get("recency", config.w_recency)),
                    "citations": float(w.get("citations", config.w_citations)),
                }
            self._scorer = RelevanceScorer(seeds, w=weights)
            # find papers with no outgoing edges (= not yet walked)
            expanded = set()
            for e in self.run.edges:
                expanded.add(e["source"])
            unwalked = [p for p in self.run.papers.values() if p.key() not in expanded and p.included]
            _emit(self.cb, phase="eligibility", msg=f"Resuming: {len(unwalked)} papers to walk.")
            # walk them as a single round (continue from current state)
            round_idx = max((p.discovered_round for p in self.run.papers.values()), default=0) + 1
            new_in_round: List[Paper] = []
            for paper in unwalked:
                if self.stop_flag.is_set():
                    break
                discovered = self._walk_paper(paper, round_idx)
                new_in_round.extend(discovered)
            self._hydrate_titles()
            if self._scorer:
                for p in new_in_round:
                    p.relevance = self._scorer.score(p)
            # relevance filter
            kept = []
            for p in new_in_round:
                if p.relevance < config.min_relevance:
                    p.included = False
                    p.excluded_reason = "low_relevance"
                else:
                    kept.append(p)
            if len(kept) > config.per_round_cap:
                kept.sort(key=lambda p: p.relevance, reverse=True)
                for p in kept[config.per_round_cap:]:
                    p.included = False
                    p.excluded_reason = "per_round_cap"
                kept = kept[: config.per_round_cap]
            self.run.phase = "included"
            self._fill_abstracts()
            self.run.status = "done"
            self.run.stats = self.run.stats_snapshot()
            _emit(self.cb, phase="included", msg=f"Resume complete: +{len(new_in_round)} papers, {len(kept)} kept.", stats=self.run.stats_snapshot())
        except Exception as exc:
            self.run.status = "error"
            self.run.error = str(exc)
            log.error("resume failed: %s\n%s", exc, traceback.format_exc())
            _emit(self.cb, phase="error", msg=f"Error: {exc}")
        finally:
            self.run.finished_at = time.time()
            save_run(self.run)

    # ------------------------------------------------------------------
    def _do_paper_mode(self):
        seeds: List[Paper] = []
        for raw in self.run.seeds_input:
            if self.stop_flag.is_set():
                break
            p = self._resolve_seed(raw, is_pdf=raw.startswith("pdf:"), )
            if p:
                p.seed = True
                p.relevance = 1.0
                seeds.append(p)
                self.run.add_paper(p)
                _emit(self.cb, phase="identification", msg=f"Seed resolved: {p.title[:60] or p.doi}", paper=p.to_dict())
        self._snowball_loop(seeds)

    # ------------------------------------------------------------------
    def _do_keyword_mode(self):
        _emit(self.cb, phase="identification", msg=f"Starting keyword mode for {self.run.keywords}")
        seeds = self._keyword_seeds(self.run.keywords, top_n=int(self.run.options.get("keyword_top_n", 8)))
        for s in seeds:
            self.run.add_paper(s)
            _emit(self.cb, phase="identification", msg=f"Seed from search: {s.title[:60]}", paper=s.to_dict())
        self._snowball_loop(seeds)

    # ------------------------------------------------------------------
    def _snowball_loop(self, seeds: List[Paper]):
        if not seeds:
            _emit(self.cb, phase="error", msg="No seed papers could be resolved.")
            return
        # fit the scorer on the seeds; allow per-run weight overrides
        weights = None
        if isinstance(self.run.options, dict) and self.run.options.get("weights"):
            w = self.run.options["weights"]
            weights = {
                "tfidf": float(w.get("tfidf", config.w_tfidf)),
                "keyword": float(w.get("keyword", config.w_keyword)),
                "recency": float(w.get("recency", config.w_recency)),
                "citations": float(w.get("citations", config.w_citations)),
            }
            _emit(self.cb, phase="screening", msg=f"Using custom relevance weights: {weights}")
        self._scorer = RelevanceScorer(seeds, w=weights)
        # score any existing papers (e.g. PDF references discovered at seed time)
        for p in self.run.papers.values():
            if not p.seed:
                p.relevance = self._scorer.score(p)
        # PRISMA screening phase
        self.run.phase = "screening"
        _emit(self.cb, phase="screening", msg=f"Scored {len(self.run.papers)} papers against {len(seeds)} seeds.")
        # the BFS queue: papers we still need to walk
        queue: List[Paper] = list(seeds)
        walked = set()
        for round_idx in range(1, config.max_iterations + 1):
            if self.stop_flag.is_set():
                _emit(self.cb, phase="eligibility", msg="Stopped by user.")
                break
            if len(self.run.papers) >= config.max_total_papers:
                _emit(self.cb, phase="eligibility", msg=f"Hit max_total_papers={config.max_total_papers}, stopping.")
                break
            if not queue:
                _emit(self.cb, phase="eligibility", msg="Queue empty, snowball converged.")
                break
            self.run.phase = "eligibility"
            _emit(
                self.cb,
                phase="eligibility",
                msg=f"Round {round_idx}: walking {len(queue)} paper(s)…",
                stats=self.run.stats_snapshot(),
            )
            new_in_round: List[Paper] = []
            for paper in list(queue):
                if self.stop_flag.is_set():
                    break
                if paper.key() in walked:
                    continue
                walked.add(paper.key())
                discovered = self._walk_paper(paper, round_idx)
                new_in_round.extend(discovered)
            # hydrate titles for any DOI-only stubs
            self._hydrate_titles()
            # score everything new
            if self._scorer:
                for p in new_in_round:
                    p.relevance = self._scorer.score(p)
            # relevance filter
            kept = []
            for p in new_in_round:
                if p.relevance < config.min_relevance:
                    p.included = False
                    p.excluded_reason = "low_relevance"
                else:
                    kept.append(p)
            # per-round cap: if too many, keep top-N by score
            if len(kept) > config.per_round_cap:
                kept.sort(key=lambda p: p.relevance, reverse=True)
                for p in kept[config.per_round_cap:]:
                    p.included = False
                    p.excluded_reason = "per_round_cap"
                kept = kept[: config.per_round_cap]
            _emit(
                self.cb,
                phase="eligibility",
                msg=f"Round {round_idx}: {len(new_in_round)} found, {len(kept)} kept (cap={config.per_round_cap}).",
                stats=self.run.stats_snapshot(),
            )
            # saturation check
            if len(kept) <= config.saturation_threshold:
                _emit(self.cb, phase="eligibility", msg="Saturation reached — stopping.")
                break
            # next round's queue = the kept papers, set their depth
            for p in kept:
                p.depth = min(p.depth or round_idx, round_idx)
            queue = kept
        # final: lazy-fill abstracts for included papers
        self.run.phase = "included"
        self._fill_abstracts()
        _emit(self.cb, phase="included", msg="Finalising corpus.", stats=self.run.stats_snapshot())

    # ------------------------------------------------------------------
    def _fill_abstracts(self):
        from .engines.openalex import OpenAlexAdapter

        oa = next((a for a in self.adapters if a.name == "openalex"), None)
        if not oa:
            return
        need = [p for p in self.run.papers.values() if p.included and not p.abstract and p.doi]
        if not need:
            return
        _emit(self.cb, phase="included", msg=f"Fetching abstracts for {len(need)} papers…")
        try:
            oa.hydrate_abstracts(need)
        except Exception as exc:
            log.warning("abstract hydration failed: %s", exc)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def start_run(
    run_id: str,
    mode: str,
    seeds_input: List[str],
    keywords: List[str],
    options: Dict,
    event_cb: Optional[EventCb] = None,
) -> Run:
    """Run snowballing on an EXISTING run row (created by the route).

    The Flask route creates the run row first (so it can return the run_id
    immediately), then calls this inside a worker thread.  Events flow
    through `event_cb` back to the SSE stream.
    """
    from .store import load_run
    run = load_run(run_id)
    if run is None:
        # fall back to creating one (legacy path)
        run = store_new_run(mode=mode, seeds_input=seeds_input, keywords=keywords, options=options)
    sb = Snowballer(run, event_cb=event_cb)
    # stash the snowballer so the route can `.stop()` it
    _RUNNERS[run.run_id] = sb
    try:
        sb.run_snowball()
    finally:
        _RUNNERS.pop(run.run_id, None)
    return run


_RUNNERS: Dict[str, Snowballer] = {}


def resume_run(run_id: str, event_cb: Optional[EventCb] = None) -> Run:
    """Resume a previously-stopped/errored run.

    Re-loads the run, re-fits the scorer on existing seeds, then walks every
    paper that has NO outgoing edges yet (i.e. hasn't been expanded).
    """
    from .store import load_run
    run = load_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    if run.status == "running":
        raise ValueError(f"run {run_id} is already running")
    sb = Snowballer(run, event_cb=event_cb)
    _RUNNERS[run.run_id] = sb
    try:
        sb.resume()
    finally:
        _RUNNERS.pop(run.run_id, None)
    return run


def stop_run(run_id: str) -> bool:
    sb = _RUNNERS.get(run_id)
    if sb:
        sb.stop()
        return True
    return False
