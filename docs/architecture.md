# CuteySnowball Architecture

A module-by-module deep dive. This document assumes you have read the
[README](../README.md) and [workflow.md](workflow.md) — it does not re-explain
what snowballing is, only **how the code is structured**.

---

## 1. The module map (16 modules)

```
cutesnowball/
├── config.py            ← all tunables (env-driven)
├── models.py            ← Paper + Run dataclasses
├── rate_limiter.py      ← per-host polite HTTP client (the anti-block core)
├── pdf_parser.py       ← pypdf + reference splitter
├── store.py             ← SQLite persistence
├── export.py            ← CSV / RIS / BibTeX / JSON / PRISMA
├── relevance.py         ← pure-Python TF-IDF + Jaccard + recency + log(cite)
├── snowball.py          ← BFS orchestrator (Wohlin 2014)
├── app.py               ← Flask app + 14 routes (incl. SSE)
└── engines/
    ├── __init__.py      ← build_adapters() factory
    ├── base.py          ← CitationAdapter ABC
    ├── openalex.py      ← cursor pagination, batch DOI hydration
    ├── semanticscholar.py  ← paged cites/references
    ├── crossref.py      ← reference[] + unstructured-citation parser
    ├── opencitations.py ← DOI-only open citation rows
    ├── scholar_scholarly.py  ← optional: scholarly + FreeProxies
    └── scholar_scrape.py    ← optional: selenium-stealth port
```

The frontend lives under `static/` (a pure HTML/CSS/JS SPA, no framework,
no build step) and is served straight by Flask. It is documented in the
README and not covered here.

---

## 2. Module-by-module

### config.py

Holds every tunable in the project as fields on a single `Config` dataclass
(mailto, source toggles, rate-limit knobs, snowball caps, relevance weights,
DB path, port, secret). Reads everything from environment variables with
sane defaults so a fresh checkout runs out of the box. Exposes a module-level
singleton `config = Config()` that every other module imports, plus the
helper `seed_sources()` returning the list of enabled adapter names.

**Key API:** `Config`, `config`, `seed_sources()`.

### models.py

The universal data shape. `Paper` is a frozen-ish dataclass normalising
everything every adapter returns (title, doi, authors, year, abstract,
venue, num_citations, sources, seed flag, depth, discovered_round,
relevance, included flag, openalex_id, scholar_id, urls, raw ref string).
`Paper.key()` is the stable identity — DOI if present, else a 12-char md5
of the lower-cased title — and is used everywhere as the corpus dict key.
`Paper.merge(other)` is the most important method: it merges another
`Paper` into self, keeping the *richer* field each time (longer abstract,
more authors, larger citation count, smaller depth, higher relevance), so
the corpus only ever gets better. `Run` holds the live state of one
snowballing session (run_id, mode, papers dict, edges list, stats snapshot,
PRISMA phase). The `PHASES = ("identification", "screening", "eligibility",
"included")` tuple is the PRISMA 4-phase list, used by both the snowball
orchestrator and the export module.

**Key API:** `Paper` (with `.key()`, `.merge()`, `.to_dict()`, `.from_dict()`),
`Run` (with `.add_paper()`, `.add_edge()`, `.has()`, `.stats_snapshot()`),
`new_run_id()`, `PHASES`.

### rate_limiter.py

The single most important anti-block safeguard. A thread-safe
`RateLimiter` that keeps one `_HostBucket` per hostname. Every external
HTTP call in CuteySnowball goes through `RateLimiter.get()`, which:

- sleeps at least `min_delay_per_host` (default 0.6s) between requests to
  the same host,
- adds random `jitter` (default 0..0.5s) so traffic looks human,
- retries on HTTP 429 with a **capped** `Retry-After` (max 5s — some free
  tiers return seconds-until-midnight which would hang the run for hours),
- retries on transient network errors with linear backoff,
- detects `scholar.google.*` and **forces a 8s floor + 6s jitter**
  regardless of the global config,
- never raises on HTTP status — callers inspect the status code.

Per-host (not global) so the safe APIs (OpenAlex, S2) aren't throttled
while waiting on the polite Crossref gap. Exposes a singleton `rate_limiter`
and a convenience `get_json()` helper that parses the body when JSON.

**Key API:** `RateLimiter`, `rate_limiter`, `rate_limiter.get(url, ...)`,
`rate_limiter.get_json(url, ...)`.

### engines/base.py

Defines `CitationAdapter`, an abstract base class with four methods that
every adapter must implement: `resolve(doi, title)` (seed → Paper),
`forward(paper)` (papers citing this one), `backward(paper)` (papers this
one cites), and optional `search(query, limit)` and `healthy()`. The
snowball orchestrator treats every adapter uniformly — it does not know or
care which API it is talking to, it just calls `backward()` / `forward()`
on each and merges the resulting `Paper` lists.

**Key API:** `CitationAdapter` (ABC).

### engines/openalex.py

The **primary** forward-snowballing source. Free, no key, generous. The
adapter knows how to (a) resolve a DOI to an OpenAlex Work, (b) pull the
`referenced_works` array (OpenAlex IDs) and batch-resolve them 50 at a
time via `filter=ids.openalex:W1|W2|…`, (c) walk the *forward* citation
list via cursor pagination on `filter=cites:{oaId}` (up to
`max_forward_pages_openalex` = 30 pages × 200 = 6 000 citing works),
(d) batch-hydrate DOIs (`hydrate_dois`, 50 per call) and lazy-fill
abstracts (`hydrate_abstracts`). OpenAlex abstracts come as an "inverted
index" (`{word: [positions]}`) — `_abstract_from_inverted()` un-inverts
them back to plain text. Mirrors the `openAlexResolveWorks` /
`openAlexResolveByDOI` / `fetchOpenAlexCiting` patterns from the upstream
BackwardForwardSnowballing project.

**Key API:** `OpenAlexAdapter` with `.resolve()`, `.backward()`,
`.forward()`, `.search()`, `.hydrate_dois()`, `.hydrate_abstracts()`.

### engines/semanticscholar.py

The second free API. Uses Semantic Scholar's dedicated
`/paper/DOI:{doi}/citations` and `/paper/DOI:{doi}/references` endpoints
(paginated, 1000 per page, up to `max_s2_pages` = 10 pages = 10 000 items)
rather than the silently-capped nested `?fields=` form. Returns full
metadata: title, externalIds (DOI + others), authors, year, abstract,
venue, citationCount, openAccessPdf. The `citingPaper` / `citedPaper`
nesting is unwrapped. No API key needed for low-volume anonymous use
(100 req / 5 min).

**Key API:** `SemanticScholarAdapter` with `.resolve()`, `.backward()`,
`.forward()`, `.search()`, internal `_paged(paper, kind)`.

### engines/crossref.py

The canonical source for a paper's deposited bibliography. Crossref is
the only one of the four free APIs that reliably has the publisher-deposited
`reference[]` array (so it's a strong backward source). The adapter parses
both structured references (with `DOI`, `article-title`, `author`, `year`)
and unstructured citation strings via the ported `_parse_unstructured_ref()`
regex parser (year + DOI + crude title extraction). Forward snowballing
returns `[]` — Crossref's forward-citation endpoint is not free, so we
defer to OpenAlex / S2 / OpenCitations. Also offers a bibliographic
`search` for keyword seed discovery. Polite-pool access via the `mailto`
parameter.

**Key API:** `CrossrefAdapter` with `.resolve()`, `.backward()`,
`.forward()` (returns `[]`), `.search()`; helper `_parse_unstructured_ref()`.

### engines/opencitations.py

Fully open citation data, but the COCI index returns rows with `citing`
and `cited` DOIs **only** — no titles, no abstracts. The adapter walks
`/citations/doi:{doi}` (forward) and `/references/doi:{doi}` (backward),
extracts the DOIs, returns a list of `Paper(doi=..., title="")` stubs.
The orchestrator pairs this with `OpenAlexAdapter.hydrate_dois()` to fill
in the titles in batches of 50. `resolve()` returns a stub (OpenCitations
has no metadata endpoint) so the orchestrator can still walk citations
even without a title.

**Key API:** `OpenCitationsAdapter` with `.resolve()` (stub-only),
`.forward()`, `.backward()`.

### engines/scholar_scholarly.py

**Optional, opt-in, off by default.** Wraps the `scholarly` PyPI package
(Unlicense). On init, builds a `ProxyGenerator` and routes *every* request
through rotating free proxies (FreeProxies) or ScraperAPI (paid, no
blocks) so the local IP is never exposed. Supports `search_pubs`,
`citedby` (forward), and `fill` — but **not** backward snowballing, so
`.backward()` returns `[]`. Catches `MaxTriesExceededException` (pause ≥1h)
and `DOSException` (pause ≥24h) and re-raises so the orchestrator can
abort the run. Healthy check returns False if `scholarly` is not installed.

**Key API:** `ScholarlyAdapter` with `.resolve()`, `.forward()`,
`.backward()` (returns `[]`), `.search()`, `.healthy()`; helpers
`_init_scholarly()`, `_ensure_init()`, `_pub_to_paper()`.

### engines/scholar_scrape.py

**Optional, opt-in, off by default.** Ports the selenium-stealth CSS
selectors from `dimitryzub/scrape-google-scholar-py` (MIT). Maintains one
headless Chrome session per adapter instance, reused. The selectors (`.gs_r.gs_or.gs_scl`
result container, `.gs_rt` title, `.gs_a` publication info, `.gs_rs`
snippet, the `Cited by` link in `.gs_ri .gs_fl a`, `.gs_or_ggsm a` PDF
link) are quoted near-verbatim from the upstream. Parses with `selectolax`
if available, else falls back to BeautifulSoup. CAPTCHA / "unusual traffic"
detection raises `RuntimeError("scholar_scrape: CAPTCHA/block detected")`
so the orchestrator can abort. Uses a real-looking User-Agent and
selenium-stealth options (languages, vendor, platform, webgl_vendor,
renderer, fix_hairline) to look human. Forward snowballing via the "Cited
by" link; backward is not supported.

**Key API:** `ScholarScrapeAdapter` with `.resolve()`, `.forward()`,
`.backward()` (returns `[]`), `.search()`, `.close()`; helper `_parse(html)`.

### snowball.py

The orchestrator. `Snowballer` runs the bi-directional BFS from Wohlin
(2014), generalised to a queue so it can run unattended. Holds the `Run`,
the list of `adapters`, a `stop_flag` (threading.Event), and the
`RelevanceScorer` (fit on the seed set). Key methods:

- `_resolve_seed(raw, is_pdf, pdf_data)` — turn a user input (DOI / title /
  PDF bytes) into a `Paper`. For PDFs, also splits the references and
  adds them as depth-0 backward children of the seed.
- `_keyword_seeds(keywords, top_n=8)` — mode B path: search every adapter,
  merge, score against the query itself, keep the top-N (with a 0.7 score
  floor so seeds survive the next filter).
- `_walk_paper(paper, round_idx)` — for one paper, call every adapter's
  `.backward()` then `.forward()`, merge new papers into the corpus, add
  directed edges.
- `_hydrate_titles()` — batch-resolve DOI-only stubs via OpenAlex.
- `_snowball_loop(seeds)` — the BFS: rounds 1..max_iterations, filter by
  min_relevance, apply per_round_cap, saturation check.
- `_fill_abstracts()` — final lazy abstract hydration for included papers.

Module-level `start_run(run_id, mode, seeds_input, keywords, options, event_cb)`
is the public entry point the Flask route calls inside a worker thread.
`stop_run(run_id)` sets the stop flag. `_RUNNERS` is a dict mapping run_id
to Snowballer so the stop route can reach into a running session.

**Key API:** `Snowballer`, `start_run()`, `stop_run()`.

### relevance.py

Pure-Python relevance scoring (no scikit-learn, no torch). `RelevanceScorer`
is constructed with the seed list, fits a `TfidfModel` on the seed titles
+ abstracts, and computes the **average seed vector**. For any candidate
paper, it computes:

```
relevance(c) = 0.45 * cos_tfidf(seed_avg, c)
             + 0.25 * jaccard(seed_keywords, c_keywords)
             + 0.15 * recency(c.year)        # 1 - exp(-(year-2000)/10)
             + 0.15 * norm_cite(c.num_citations)  # log1p saturating at 1000
```

Tokenization: lowercase, regex `[a-z0-9][a-z0-9\-]{2,}`, drop a small
English stoplist. `keywords_of(paper)` builds the keyword set with the
title weighted 3x (`(title + " ") * 3 + abstract`). `TfidfModel._vec()`
uses sublinear TF (`1 + log(count)`) times standard IDF. Cosine is
computed via sparse dicts (small × large iteration) so it is fast on
long abstracts. The full breakdown (with worked example) is in
[relevance.md](relevance.md).

**Key API:** `RelevanceScorer` (with `.score()`, `.score_many()`),
`TfidfModel` (with `.fit()`, `.cosine_vs_seed()`), `tokenize()`,
`keywords_of()`, `jaccard()`.

### pdf_parser.py

Pure-Python PDF reference extraction using `pypdf` (no native code, no
CDN — unlike the upstream JS tool which uses Mozilla pdf.js). The flow
is:

1. `extract_text_from_pdf(data)` — concatenate every page's text.
2. Find the first DOI in the first ~8000 chars (that is usually the
   paper itself).
3. Find the **References** / **Bibliography** heading (anchored on its
   own line), cut at the first Appendix / Acknowledgements.
4. Try both splitters — `_split_numbered()` for `[1]`/`1.`/`(1)` style,
   and `_split_apa()` for `Surname, Initials. (Year).` style — pick the
   one yielding more entries (≥ 3).
5. `_parse_one(ref)` per entry: regex out the DOI, the year, and a
   best-effort title; build a `Paper` with `sources=["pdf"]`.
6. Dedup by the raw ref text.

Same limitation as the upstream: scanned image PDFs have no text layer
and return `[]` — provide the DOI instead.

**Key API:** `extract_references_from_pdf(data)` → `(doi, [Paper])`,
`extract_text_from_pdf(data)`.

### store.py

SQLite persistence so the UI can reload a finished/running run after a
page refresh and so long runs can survive process restarts. The `runs`
table has one row per run: `run_id` (PK), `mode`, `status`, `phase`,
`message`, `created_at`, `started_at`, `finished_at`, `data` (the full
Run serialised as JSON), `error`. Thread-safe via a module-level lock.
`save_run()` upserts; `load_run()` deserialises; `list_runs()` returns
recent runs for the sidebar. The DB path defaults to
`~/.cuteysnowball/runs.sqlite` and is created on first call.

**Key API:** `init_db()`, `save_run(run)`, `load_run(run_id)`,
`list_runs(limit=20)`, `new_run(mode, seeds_input, keywords, options)`.

### export.py

Pure-Python exporters writing to in-memory strings (no external deps —
BibTeX is hand-rolled so we don't pull in the heavy `bibtexparser` that
`scholarly` uses):

- `export_csv(run, include_abstracts, only_included)` — Excel-safe (UTF-8
  BOM, newline scrubbing), one row per included paper.
- `export_ris(run)` — for Zotero / EndNote / Mendeley import.
- `export_bibtex(run)` — minimal hand-rolled encoder; keys are
  `surnameyear1` so they are reasonably citeable.
- `export_json(run)` — full snapshot **plus** a `graph` object with
  `nodes` and `edges` (machine-readable, directed-graph consumer-ready).
- `prisma_counts(run)` — the four PRISMA phase counts
  (identification / screening / eligibility / included).

**Key API:** `export_csv`, `export_ris`, `export_bibtex`,
`export_json`, `prisma_counts`.

### app.py

The Flask app factory. Creates the app, inits the SQLite store, serves
the static SPA from `/`, and exposes 14 routes — 6 read-only (`/api/config`,
`/api/sources`, `/api/health`, `/api/run/<id>`, `/api/run/<id>/stats`,
`/api/run/<id>/prisma`, `/api/runs`), one quick-search (`POST /api/search`),
one run-creator (`POST /api/run`, JSON **or** multipart with PDFs), one
SSE stream (`GET /api/run/<id>/events`), one stop (`POST /api/run/<id>/stop`),
one export (`GET /api/run/<id>/export?format=...`). The SSE route drains a
per-run `queue.Queue` that the worker thread fills via the `event_cb`
callback. Every long-running thing happens in a daemon thread; the HTTP
handler returns immediately. Static files (`static/`) are served straight
— the SPA is pure HTML/CSS/JS, no build step.

**Key API:** `create_app(static_folder=None)`, internal `_get_queue(run_id)`,
`_drop_queue(run_id)`.

### engines/__init__.py

The factory. `build_adapters(cfg)` returns a list of adapter instances
honouring the config toggles (`enable_openalex`, `enable_semantic_scholar`,
`enable_crossref`, `enable_opencitations`, `enable_scholarly`,
`enable_scholar_scrape`). The two Scholar adapters are lazy-imported inside
the function so the project still imports cleanly even if `scholarly` /
`selenium-stealth` are not installed.

**Key API:** `build_adapters(cfg)` → `list[CitationAdapter]`.

---

## 3. Dependency diagram (who imports whom)

```
                    ┌──────────────┐
                    │  config.py  │  (no imports inside cutesnowball)
                    └──────┬──────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────────┐
        │ models.py│  │rate_limiter│ │  (stdlib)    │
        └─────┬────┘  └─────┬─────┘  └──────────────┘
              │             │
              │             │
   ┌──────────┴─────────── │ ─────────────────────────────────────┐
   │                       │                                         │
   ▼                       ▼                                         ▼
┌─────────────┐     ┌─────────────┐                          ┌─────────────┐
│engines/base │     │ relevance  │                          │ pdf_parser  │
└──────┬──────┘     └──────┬──────┘                          └──────┬──────┘
       │                   │                                        │
       │                   │                                        │
       ▼                   │                                        │
┌─────────────────────────────┐                                     │
│ engines/{openalex,          │                                     │
│   semanticscholar,          │                                     │
│   crossref, opencitations,  │                                     │
│   scholar_scholarly,        │                                     │
│   scholar_scrape}           │                                     │
│  each imports:              │                                     │
│   base, config, models,     │                                     │
│   rate_limiter              │                                     │
└──────────┬──────────────────┘                                     │
           │                                                        │
           ▼                                                        │
       ┌─────────────┐                                              │
       │  snowball   │◄───────────────────── relevance ─────────────┤
       │  (orchestrator)                                            │
       │  imports:                                                  │
       │   config, engines, models,                                │
       │   rate_limiter, relevance, store, pdf_parser (lazy)      │
       └──────┬──────┘                                              │
              │                                                     │
              ▼                                                     │
       ┌─────────────┐                                              │
       │   store     │  (imports config, models)                   │
       └──────┬──────┘                                              │
              │                                                     │
              ▼                                                     │
       ┌─────────────┐                                              │
       │   export    │  (imports models — pure stdlib)              │
       └──────┬──────┘                                              │
              │                                                     │
              ▼                                                     │
       ┌─────────────┐                                              │
       │    app      │  imports: config, engines, models, store,   │
       │  (Flask)   │          snowball, export                    │
       └─────────────┘
```

The dependency graph is acyclic and shallow: `app` → `snowball` →
{`engines`, `relevance`, `store`, `pdf_parser`}; each of those →
{`config`, `models`, `rate_limiter`}; and `config` / `models` /
`rate_limiter` are leaves. That makes the codebase easy to test in
isolation — you can exercise `relevance.py` with no network, the engines
with no Flask, etc.

---

## 4. Request-flow diagram (one browser click → external APIs → back)

```
  Browser (SPA)
      │
      │  1. POST /api/run  {mode, seeds, keywords, options}
      │     (or multipart: dois, pdfs[], options)
      ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                       Flask  (app.py)                            │
  │                                                                  │
  │  2. store_mod.new_run(...)         → SQLite INSERT (run row)     │
  │  3. _get_queue(run_id)             → per-run queue.Queue         │
  │  4. threading.Thread(worker).start()                             │
  │  5. return {"run_id": "...", "status":"started"} (immediately)   │
  └────────────────────┬─────────────────────────────────────────────┘
                       │
                       │ (in the worker thread)
                       ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │            snowball_mod.start_run(run_id, ...)                   │
  │                                                                  │
  │  6. store.load_run(run_id)             → SQLite SELECT          │
  │  7. Snowballer(run, event_cb=cb)                                │
  │  8. sb.run_snowball()                                            │
  │     │                                                            │
  │     │  _resolve_seed / _keyword_seeds                            │
  │     │     │                                                     │
  │     │     ▼  (per adapter)                                      │
  │     │   ┌────────────────────────────────────────────┐          │
  │     │   │ adapter.resolve / search / backward /       │          │
  │     │   │   forward                                  │          │
  │     │   │   │                                        │          │
  │     │   │   ▼                                        │          │
  │     │   │  rate_limiter.get_json(url)                │          │
  │     │   │   │                                        │          │
  │     │   │   ▼                                        │          │
  │     │   │  ┌─────────────────────────────────────┐    │          │
  │     │   │  │ per-host bucket:                    │    │          │
  │     │   │  │   sleep(min_delay + jitter)         │    │          │
  │     │   │  │   requests.get(...)                 │    │          │
  │     │   │  │   on 429: cap Retry-After to 5s     │    │          │
  │     │   │  │   on net error: linear backoff      │    │          │
  │     │   │  └─────────────────────────────────────┘    │          │
  │     │   │   │                                        │          │
  │     │   │   ▼                                        │          │
  │     │   │  External API (OpenAlex / S2 / Crossref   │          │
  │     │   │   / OpenCitations / Scholar)              │          │
  │     │   │   │                                        │          │
  │     │   │   ▼                                        │          │
  │     │   │  JSON response                             │          │
  │     │   └────────────────────────────────────────────┘          │
  │     │                                                            │
  │     │  9. merge new papers into run.papers                       │
  │     │ 10. run.add_edge(...) for forward/backward                 │
  │     │ 11. _emit(cb, phase=..., msg=..., stats=...)               │
  │     │                                                            │
  │     │  ── callback puts event on the per-run queue ──►  (see SSE)
  │     │                                                            │
  │     │ 12. _hydrate_titles / _fill_abstracts (more adapter calls)│
  │     │ 13. store.save_run(run)   → SQLite UPSERT                 │
  │     │ 14. queue.put({"_done": True})                            │
  └──────────────────────────────────────────────────────────────────┘
                       │
                       │ (concurrently, the SSE route)
                       ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │           GET /api/run/<id>/events   (text/event-stream)         │
  │                                                                  │
  │  - drains the per-run queue                                       │
  │  - on every event: yield "event: progress\ndata: {json}\n\n"    │
  │  - on _done sentinel: load final run from SQLite,                │
  │                       yield "event: snapshot\ndata: {json}\n\n"  │
  │                       yield "event: done\ndata: {}\n\n"          │
  │  - sends ": ping" every 15s while idle                            │
  └────────────────────────┬─────────────────────────────────────────┘
                           │
                           ▼
                       Browser (SPA)
                       api.js consumes the SSE stream, updates the UI
                       graph / list / tree / table live as events arrive
```

A few invariants worth knowing:

- **The Flask route returns immediately.** The run_id is given to the
  browser before any external API is called. The browser then opens a
  second connection — the SSE stream — to watch progress in real time.
- **Every external HTTP call funnels through `rate_limiter`.** No adapter
  ever calls `requests` directly. This is what makes the per-host
  politeness guarantees enforceable in one place.
- **Persistence is write-through.** Every phase transition calls
  `save_run(run)`, so if the process dies the run can be resumed from
  SQLite by the next `/api/run/<id>` request.
- **Stopping is cooperative.** `POST /api/run/<id>/stop` sets a
  `threading.Event` flag; the orchestrator checks it at the top of every
  loop iteration and at the top of every adapter call, then breaks
  cleanly. There is no `Thread.kill()`.
