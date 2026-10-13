# CuteySnowball

> Python tool for **Forward &amp; Backward Snowballing** of academic
> papers — for Systematic Literature Reviews (SLR) and Systematic Mapping
> Studies (SMS).

<img width="255" alt="CuteySnowball-logo" src="./static/img/logo.png" />

CuteySnowball takes one or more **seed papers** (by DOI or PDF) **or a keyword
query**, walks the citation graph in **both directions** — *forward* (who cites
this?) and *backward* (what does this cite?) — scores every candidate for
**relevance**, and hands you a tidy, machine-readable corpus with a
**directed timeline graph** you can actually read.

It is built on top of three open-source projects and the standard SLR/SMS
methodology:

- **[BackwardForwardSnowballing](https://github.com/abequet/BackwardForwardSnowballing)**
  by Adolphe Béquet (MIT) — the conceptual ancestor; a manual, browser-based
  snowballing UI. CuteySnowball reuses its unified-paper model, its
  OpenAlex/Semantic-Scholar/Crossref/OpenCitations query patterns, its
  numbered-vs-APA PDF reference splitter, and its batched-DOI hydration
  technique.
- **[scrape-google-scholar-py](https://github.com/dimitryzub/scrape-google-scholar-py)**
  by Dmitiry Zub (MIT) — a selenium-stealth Google Scholar scraper. CuteySnowball
  ports its organic-SERP CSS selectors and its `selenium-stealth` boilerplate as
  an **optional** Google Scholar enrichment backend.
- **[scholarly](https://github.com/scholarly-python-package/scholarly)**
  (Unlicense) — the most mature Python Google Scholar client, with proxy/Tor/
  CAPTCHA support. CuteySnowball wraps its `search_pubs` / `citedby` / `fill`
  APIs as another **optional** Google Scholar enrichment backend.

The methodology is grounded in:

- Kitchenham (2004), *Procedures for Performing Systematic Reviews*.
- Kitchenham &amp; Charters (2007), *Guidelines for performing SLRs in SE*.
- Petersen et al. (2008 / 2015), *Systematic Mapping Studies in SE*.
- Jalali &amp; Wohlin (2012), *Database searches vs. backward snowballing*.
- Wohlin (2014), *Guidelines for snowballing in systematic literature studies*.
- Page et al. (2021), *The PRISMA 2020 statement*.

See [`docs/references.md`](docs/references.md) for the full citation list.

---

## Features

- **Two start modes**
  1. **Paper mode** — seed from one or more DOIs or PDFs.
  2. **Keyword mode** — search across OpenAlex + Semantic Scholar + Crossref,
     pick the top relevant hits as seeds, then snowball each.
- **Bi-directional snowballing** (Wohlin 2014) with a queue-based BFS that runs
  unattended, scoring and filtering every round.
- **Four free academic APIs by default** — OpenAlex, Semantic Scholar,
  Crossref, OpenCitations. **Zero IP-block risk** out of the box.
- **Optional Google Scholar enrichment** — `scholarly` (proxy-rotated) and a
  port of `scrape-google-scholar-py` (selenium-stealth), both **off by default**.
- **Pure-Python relevance score** (no scikit-learn / torch):
  `0.45·TF-IDF + 0.25·keyword-Jaccard + 0.15·recency + 0.15·log(citations)`.
- **Per-round cap** — when a snowball round floods (e.g. a 1000-cite paper),
  only the top-N most relevant survive to the next round, so the crawl stays
  finite without throwing away the long tail.
- **Saturation stopping** — the run ends automatically when a round yields ≤ 1
  new eligible paper (or `max_iterations` / `max_total_papers` is hit).
- **Directed timeline graph** — pure-SVG, no D3/vis/CDN. X = publication year,
  Y = snowball depth. Pan, zoom, fit, hover-tooltip, forward/backward edge
  toggles.
- **Four views of the same corpus** — directed graph, relevance-ranked list,
  citation hierarchy tree, sortable table.
- **Machine-readable exports** — JSON (with full graph + edges), CSV (Excel
  BOM), RIS (Zotero/EndNote), BibTeX. Abstracts included where available.
- **PRISMA-style 4-phase flow** (Identification → Screening → Eligibility →
  Included) shown live during a run.
- **SQLite persistence** — refresh the page, your run is still there.
- **Pure HTML/CSS/JS frontend** — no framework, no CDN, no build step. Just
  static files served by Flask.
- **GPL-3.0** licensed.

---

## Quick start

Install and go to project directory:
```bash
git clone https://github.com/TadavomnisT/CuteySnowball.git
cd CuteySnowball
```
Install dependencies and Run the project using:
```bash
# 1. (optional) make a venv
python3 -m venv .venv && source .venv/bin/activate

# 2. install
pip install -r requirements.txt

# 3. run
python3 run.py
# → open http://localhost:5000
```

Then:

1. Pick **"Start from paper(s)"** and paste a DOI (e.g. `10.1145/2568225.2568315`)
   or drop a PDF — *or* pick **"Start from keywords"** and type a query.
2. (Advanced) tune `max_iterations`, `min_relevance`, `per_round_cap`.
3. Hit **Start snowballing ▸**.
4. Watch the live PRISMA-style progress, then explore the graph / ranked list /
   tree / table. Filter by relevance, year, text. Export when ready.

---

## Configuration

Everything is tunable via environment variables (see
[`cutesnowball/config.py`](cutesnowball/config.py)):

| Variable | Default | Meaning |
|---|---|---|
| `CUTESNOWBALL_PORT` | `5000` | Flask port |
| `CUTESNOWBALL_MAILTO` | `cuteysnowball@example.org` | Crossref/OpenAlex polite-pool address — **set this to your real email** |
| `CUTESNOWBALL_ENABLE_OPENALEX` | `1` | Free API (recommended on) |
| `CUTESNOWBALL_ENABLE_S2` | `1` | Free API (recommended on) |
| `CUTESNOWBALL_ENABLE_CROSSREF` | `1` | Free API (recommended on) |
| `CUTESNOWBALL_ENABLE_OPENCITATIONS` | `1` | Free API (recommended on) |
| `CUTESNOWBALL_ENABLE_SCHOLARLY` | `0` | Google Scholar via `scholarly` (**opt-in, blocking risk**) |
| `CUTESNOWBALL_ENABLE_SCHOLAR_SCRAPE` | `0` | Google Scholar via selenium (**opt-in, blocking risk**) |
| `CUTESNOWBALL_SCHOLAR_PROXY` | `free` | `free` (FreeProxies) · `scraperapi` · `none` |
| `CUTESNOWBALL_SCRAPERAPI_KEY` | `""` | ScraperAPI key (paid, no blocks) |
| `CUTESNOWBALL_MIN_DELAY` | `0.6` | Min seconds between requests to the same host |
| `CUTESNOWBALL_JITTER` | `0.5` | Random jitter added to every delay |
| `CUTESNOWBALL_BACKOFF_429` | `5.0` | Base backoff on HTTP 429 (capped at 5s) |
| `CUTESNOWBALL_MAX_RETRIES` | `3` | Max retries per request (network errors / 5xx) |
| `CUTESNOWBALL_DEBUG` | `0` | Verbose logging |

---

## Anti-block by design

CuteySnowball is **safe by default**. The four enabled APIs are free, key-less,
scholarly services that never block your IP:

| Source | Auth | Rate limit | Block risk |
|---|---|---|---|
| **OpenAlex** | none (mailto polite) | 100k/day soft | none |
| **Semantic Scholar** | none | 100 req / 5 min anon | none (429 on burst, auto-handled) |
| **Crossref** | none (mailto polite) | 50 req/s polite pool | none |
| **OpenCitations** | none | generous | none |
| Google Scholar (`scholarly`) | proxy | **aggressive** | **high — opt-in only** |
| Google Scholar (`scrape`) | selenium | **aggressive** | **high — opt-in only** |

When Google Scholar is enabled, CuteySnowball:

- routes **every** request through rotating free proxies (or your ScraperAPI
  key),
- enforces an **8-second floor + 6-second jitter** between requests to
  `scholar.google.com` (10× stricter than the free APIs),
- detects CAPTCHA / "unusual traffic" pages and aborts the run rather than
  hammering through,
- respects `Retry-After` (capped at 5s — we don't honour the
  seconds-until-midnight reset literally),
- falls back to the next source on any failure.

See [`docs/anti-block.md`](docs/anti-block.md) for the full strategy.

---

## Project layout

```
CuteySnowball/
├── run.py                       # entry point: python3 run.py
├── requirements.txt
├── LICENSE                      # GPL-3.0
├── README.md
├── cutesnowball/
│   ├── app.py                   # Flask app + 14 routes (incl. SSE)
│   ├── config.py                # all tunables
│   ├── models.py                # Paper dataclass + Run state
│   ├── rate_limiter.py          # per-host polite limiter (the anti-block core)
│   ├── snowball.py              # SBS BFS orchestrator
│   ├── relevance.py             # pure-Python TF-IDF + Jaccard + recency
│   ├── pdf_parser.py            # pypdf + numbered/APA reference splitter
│   ├── store.py                 # SQLite run persistence
│   ├── export.py                # CSV / RIS / BibTeX / JSON graph / PRISMA
│   └── engines/
│       ├── base.py              # CitationAdapter interface
│       ├── openalex.py          # cursor pagination, batch DOI hydration
│       ├── semanticscholar.py   # paged cites/references
│       ├── crossref.py          # reference[] + unstructured-citation parser
│       ├── opencitations.py     # DOI-only open citation data
│       ├── scholar_scholarly.py # optional: scholarly + FreeProxies
│       └── scholar_scrape.py    # optional: selenium-stealth port
├── static/
│   ├── index.html               # the SPA shell
│   ├── css/style.css            # pure CSS, light/dark, responsive
│   ├── js/
│   │   ├── utils.js             # helpers (no deps)
│   │   ├── api.js               # fetch + SSE consumer
│   │   ├── graph.js             # pure-SVG directed graph renderer
│   │   └── app.js               # SPA controller
│   └── img/favicon.svg
├── docs/
│   ├── workflow.md              # the full snowball workflow, explained simply
│   ├── architecture.md          # module-by-module deep dive
│   ├── anti-block.md            # how we avoid IP bans
│   ├── relevance.md             # how the score is computed
│   └── references.md            # SLR/SMS/snowballing citations
└── examples/
    └── sample_dois.txt
```

---

## API

All routes are JSON over HTTP. SSE for live progress.

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `GET` | `/api/config` | — | enabled sources, limits, weights |
| `GET` | `/api/sources` | — | per-adapter health |
| `GET` | `/api/health` | — | `{status:"ok"}` |
| `POST` | `/api/search` | `{query, limit}` | search results from all sources |
| `POST` | `/api/run` | `{mode, seeds, keywords, options}` *or* multipart form (dois, pdfs[], options) | `{run_id}` |
| `GET` | `/api/run/<id>` | — | full run snapshot (papers, edges, stats) |
| `GET` | `/api/run/<id>/stats` | — | PRISMA counts + totals |
| `GET` | `/api/run/<id>/events` | — | **SSE** stream of progress events |
| `POST` | `/api/run/<id>/stop` | — | `{stopped: bool}` |
| `GET` | `/api/run/<id>/export` | `?format=ris\|csv\|json\|bibtex&all=0&abstracts=1` | file download |
| `GET` | `/api/run/<id>/prisma` | — | 4-phase PRISMA counts |
| `GET` | `/api/runs` | — | recent runs |

### Start a run (paper mode, JSON)

```bash
curl -X POST http://localhost:5000/api/run \
  -H 'Content-Type: application/json' \
  -d '{"mode":"paper","seeds":["10.1145/2568225.2568315"],"keywords":[],
       "options":{"max_iterations":3,"min_relevance":0.2,"per_round_cap":30}}'
# -> {"run_id":"3aab40178db6","status":"started"}
```

### Stream progress (SSE)

```bash
curl -N http://localhost:5000/api/run/3aab40178db6/events
# event: progress
# data: {"ts":...,"phase":"eligibility","msg":"Round 1: walking 1 paper(s)…","stats":{...}}
# event: snapshot
# data: { ... full run ... }
# event: done
# data: {}
```

### Export

```bash
curl -OJ http://localhost:5000/api/run/3aab40178db6/export?format=json
curl -OJ http://localhost:5000/api/run/3aab40178db6/export?format=csv
curl -OJ http://localhost:5000/api/run/3aab40178db6/export?format=ris
curl -OJ http://localhost:5000/api/run/3aab40178db6/export?format=bibtex
```

---

## How it works (30-second version)

1. **Seed.** You give DOIs/PDFs or a keyword query. In keyword mode we search
   all enabled sources, score the hits, keep the top-N as seeds.
2. **Score the seeds.** Fit a TF-IDF model on the seed titles+abstracts.
3. **Snowball (BFS).** For every paper in the queue, ask every source for its
   *references* (backward) and its *citations* (forward). Merge new hits into
   the corpus (richer fields win). Add citation edges. Score the new hits.
4. **Filter.** Drop anything below `min_relevance`. If a round overflowed, keep
   only the top-`per_round_cap` by score for the next round's queue (the rest
   stay in the corpus, marked excluded).
5. **Stop.** When a round yields ≤ 1 new eligible paper (saturation), or
   `max_iterations` / `max_total_papers` is hit.
6. **Hydrate.** Lazy-fill abstracts from OpenAlex for any paper still missing
   one.
7. **Export.** JSON (with graph + edges), CSV, RIS, BibTeX.

Read [`docs/workflow.md`](docs/workflow.md) for the detailed, plain-English
walkthrough and [`docs/architecture.md`](docs/architecture.md) for the
module-by-module deep dive.

---

## Acknowledgements

CuteySnowball stands on the shoulders of:

- **Adolphe Béquet** — [BackwardForwardSnowballing](https://github.com/abequet/BackwardForwardSnowballing) (MIT)
- **Dmitiry Zub** — [scrape-google-scholar-py](https://github.com/dimitryzub/scrape-google-scholar-py) (MIT)
- **the scholarly maintainers** — [scholarly](https://github.com/scholarly-python-package/scholarly) (Unlicense)
- **OpenAlex**, **Semantic Scholar**, **Crossref**, **OpenCitations** — the free,
  open scholarly infrastructure that makes this possible without any scraping.
- **Kitchenham, Petersen, Wohlin, Page et al.** — the SLR/SMS/snowballing/PRISMA
 methodology.

Data source attribution (per the Semantic Scholar API terms): *CuteySnowball
retrieves citation data from the Semantic Scholar Graph API, OpenAlex, Crossref,
and OpenCitations.*

---

## Limits &amp; caveats

- **Scanned PDFs** have no text layer; the PDF reference parser returns nothing
  (same limitation as Mozilla pdf.js). Provide the DOI instead.
- **Recent papers** (last ~1 week) may be missing from the forward indexes.
- **Google Scholar enrichment** is opt-in because Scholar bans IPs that issue
  many `search_pubs`/`citedby` queries. Use a proxy. Even then, expect
  intermittent CAPTCHAs.
- **Relevance is a heuristic**, not a gold standard — the snowballing
  literature (Wohlin 2014) prescribes *qualitative* inclusion, not a numeric
  score. Treat the score as a ranking aid.
- This is a **research tool**, not medical / legal / clinical evidence
  synthesis software.

---

## License

**GNU General Public License v3.0** — see [`LICENSE`](LICENSE). CuteySnowball is
free software: you can redistribute it and/or modify it under the terms of the
GPL v3. The upstream projects retain their own licenses (MIT / Unlicense) and
are acknowledged above and in [`docs/references.md`](docs/references.md).
