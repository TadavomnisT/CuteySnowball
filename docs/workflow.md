# The CuteySnowball Workflow

This document explains, in plain English, exactly what happens from the
moment you click **"Start snowballing"** to the moment you see the finished
corpus. No jargon, no academic shorthand — just the steps, the why, and a
diagram.

If you only have 60 seconds, read the [30-second version in the README](../README.md#-how-it-works-30-second-version)
first, then come back here for the detail.

---

## 1. The two ways to start

CuteySnowball has two **start modes**. You pick one in the web UI.

### Mode A — "Start from paper(s)"

You already have one or more papers you care about (you read them, they
were assigned to you, a colleague pointed you at them). You give them to
CuteySnowball as:

- **DOIs** — strings like `10.1145/2568225.2568315`. Paste one per line in
  the box. CuteySnowball resolves each DOI via OpenAlex, Semantic Scholar,
  Crossref (whichever answers first) and pulls down the full metadata:
  title, authors, year, abstract, citation count.
- **PDF files** — drop one or more PDFs. CuteySnowball uses `pypdf` to
  extract text, finds the first DOI in the first few pages (that is usually
  the paper itself), then locates the **References** section and splits it
  into individual entries using both the numbered style (`[1] Author et al…`)
  and the APA style (`Surname, I. (2020). Title…`). Each parsed reference
  becomes a "backward" child of the seed paper, at depth 0, before the
  snowball even starts.

These resolved papers are the **seed set**. They are marked `seed=True`
and given a relevance of `1.0` (in paper mode) — they are the source of
truth, the centre of the universe for this run.

### Mode B — "Start from keywords"

You don't have a paper yet — you have a topic. Type a query like
`"microservices performance benchmarking"`. CuteySnowball:

1. Sends that query to every enabled source (OpenAlex, Semantic Scholar,
   Crossref, optionally Scholar).
2. Merges the results by DOI / title-hash so duplicates collapse into one
   record (taking the richest fields from each source).
3. Builds a temporary relevance scorer whose "seed corpus" is just the
   query string itself.
4. Scores every candidate, sorts by score, and keeps the top **N**
   (default 8 — controlled by the `keyword_top_n` option).
5. Marks each survivor as a seed, but **clamps its score to at least 0.7**
   so the relevance filter in the next stage doesn't immediately drop the
   seeds you just picked.

After either mode you end up with the same thing: **a seed set of `Paper`
objects**, sitting in the run, ready to snowball.

---

## 2. Forward vs Backward snowballing — a concrete example

Snowballing is just walking the citation graph in two directions. Imagine
this paper as your seed:

> **"MapReduce: Simplified Data Processing on Large Clusters"**
> Dean & Ghemawat, OSDI 2004 — DOI `10.1145/1251254.1251263`

This paper has its own bibliography (the things it cites), and other
papers cite it (the things that came after). The two directions are:

- **Backward** = look at this paper's *references*.
  "What did Dean & Ghemawat build on?"
  → You'd find papers like *GFS* (Ghemawat et al., 2003),
  *Sort* (Knuth, 1973), *MPI*, *database sharding papers*, etc.

- **Forward** = look at this paper's *citations*.
  "Who built on Dean & Ghemawat afterwards?"
  → You'd find hundreds of follow-ups — *Spark* (Zaharia et al. 2010),
  *Hadoop*, *Dryad*, *FlumeJava*, and on and on.

CuteySnowball walks **both directions** for every paper it picks up. That
is what makes it "bi-directional snowballing" — the name comes from
Wohlin (2014), see [references.md](references.md).

A real run can grow quickly: a famous paper like MapReduce has thousands
of citations. That is why CuteySnowball has **caps** (next section).

---

## 3. The BFS queue, rounds, the per-round cap, and saturation

The snowball loop is a **breadth-first search (BFS)**. Think of it like
this:

> You are exploring a cave system. The seed papers are the cave entrance.
> Each "round" you light up everything one tunnel further in. You don't go
> deep down one tunnel first — you sweep outward evenly. You also drop a
> rope behind you so you don't re-explore the same cave.

The concrete loop (in `cutesnowball/snowball.py`, `_snowball_loop`):

1. **Build the queue.** Initially, the queue = the seed set.
2. **Round r = 1, 2, … up to `max_iterations` (default 5).**
   For every paper currently in the queue, in order:
   - Ask every adapter for its **references** (backward) — each new paper
     found becomes the *target* of a `backward` edge from this paper.
   - Ask every adapter for its **citations** (forward) — each new paper
     found becomes the *source* of a `forward` edge pointing at this paper.
   - Merge new papers into the corpus. `Paper.merge()` keeps the richer
     field each time (longer abstract, more authors, higher citation count,
     etc.), so the corpus only ever gets *better*, never worse.
3. **Hydrate titles.** Some sources (especially OpenCitations) give only
   DOIs. After every round we batch-resolve those DOIs through OpenAlex
   (50 per request) to fill in the titles.
4. **Score the round's new papers** with the `RelevanceScorer` (see
   [relevance.md](relevance.md)).
5. **Filter.** Anything below `min_relevance` (default `0.18`) is marked
   `excluded_reason="low_relevance"`. It stays in the corpus (you can still
   see it, export it, graph it) but it does not go into the next round's
   queue.
6. **Per-round cap.** If the round produced more than `per_round_cap`
   survivors (default `60`), sort them by score and keep only the top N.
   The rest are marked `excluded_reason="per_round_cap"` — they also stay
   in the corpus, but they are not walked further. This is the **safety
   valve** against flood: a 1 000-citation seed paper would otherwise pull
   in 1 000 new papers, all of which could each pull in 1 000 more — the
   crawl would explode. The cap keeps it finite without throwing away the
   long tail (everything is still recorded, just not explored further).
7. **Saturation check.** If this round kept ≤ `saturation_threshold`
   survivors (default `1`), the run is **saturated**: there is nothing
   more to discover. Stop early.
8. **Next round's queue** = the survivors of this round. Set their `depth`
   to the current round (the BFS depth from the nearest seed).
9. Loop back to step 2, **or** stop if:
   - the user clicked **Stop**,
   - the corpus hit `max_total_papers` (default `500`), or
   - `max_iterations` (default `5`) was reached.

---

## 4. The PRISMA 4-phase mapping

PRISMA 2020 (Page et al.) is the standard reporting checklist for
systematic reviews. It splits a review into four phases. CuteySnowball
maps to them like this:

```
┌─────────────────────────────┐
│  1. IDENTIFICATION          │  Search + snowball discovery
│                             │
│  - In paper mode:   seeds (user-supplied DOIs / PDFs)
│  - In keyword mode: search across OpenAlex / S2 / Crossref / Scholar
│                      → top-N kept as seeds
│  - During snowball: every new ref / citation is "identified"
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  2. SCREENING               │  Relevance scoring + low-relevance filter
│                             │
│  - Fit TF-IDF model on seeds
│  - Score every paper 0..1
│  - Drop papers below `min_relevance`
│    (excluded_reason = "low_relevance")
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  3. ELIGIBILITY             │  Per-round cap + saturation check
│                             │
│  - If a round overflowed, keep only the top-`per_round_cap`
│  - Anything trimmed here has excluded_reason = "per_round_cap"
│  - Saturation (≤ 1 new eligible) ends the run
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│  4. INCLUDED                │  Final corpus with abstracts hydrated
│                             │
│  - Lazy abstract fetch from OpenAlex for any paper still missing one
│  - Status: done, phase: "included"
│  - Ready for export (JSON / CSV / RIS / BibTeX)
└─────────────────────────────┘
```

The live progress bar in the UI shows which phase you are in. The `/api/run/<id>/prisma`
endpoint returns the four counts programmatically — useful for pasting
straight into a PRISMA flow diagram for a thesis or paper.

---

## 5. Abstract hydration at the end

Some sources don't return abstracts (OpenCitations, Google Scholar via
`scrape`). Others return abstracts as an "inverted index" (OpenAlex) which
CuteySnowball un-inverts back to plain text on the fly. But for papers that
came through a DOI-only path, the abstract field can still be empty.

After the snowball loop finishes, CuteySnowball runs one final pass over
every **included** paper that is still missing an abstract and:

1. Sends the DOIs to OpenAlex in batches of 50
   (`https://api.openalex.org/works?filter=doi:a|b|c|...`).
2. Reconstructs each abstract from the inverted index.
3. Writes it back into the `Paper.abstract` field via `merge()`.

This is the "lazy hydration" pattern ported from the upstream
BackwardForwardSnowballing project — it is lazy because we only pay the
abstract-fetch cost for papers that *survived* the relevance filter, not
for the thousands that got dropped.

---

## 6. Numbered step list (the whole thing in 12 steps)

If you want to explain CuteySnowball to a colleague in one breath:

1. User picks mode A (paper / PDF) or mode B (keyword).
2. CuteySnowball resolves the seeds into full `Paper` records.
3. In keyword mode, the top-N search results become the seeds.
4. The relevance scorer is **fit** on the seed corpus (TF-IDF + keyword set).
5. Every existing paper (including PDF refs) is scored.
6. Round 1 starts: queue = seeds.
7. For each paper in the queue, ask every adapter for refs (backward) +
   citations (forward).
8. Merge new papers into the corpus; record directed edges.
9. Hydrate DOI-only titles from OpenAlex (50 per batch).
10. Score the new papers; drop below `min_relevance`.
11. If survivors > `per_round_cap`, keep top-N by score; mark the rest as
    `per_round_cap`.
12. If survivors ≤ 1 (saturation) or `max_iterations` reached, stop. Else
    loop back to step 7 with the new queue.
13. Final: lazy-fill abstracts for every included paper from OpenAlex.
14. Mark run `done`, persist to SQLite, emit the final `snapshot` event.

---

## 7. ASCII flow diagram

```
                  ┌────────────────────────────────────┐
                  │      USER (browser, SPA)           │
                  │  picks DOI/PDF  or  keyword query   │
                  └─────────────────┬──────────────────┘
                                    │ POST /api/run
                                    ▼
                  ┌────────────────────────────────────┐
                  │        Flask  (app.py)              │
                  │  creates Run row, spawns worker     │
                  └─────────────────┬──────────────────┘
                                    │ start_run(run_id, ...)
                                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                  Snowballer  (snowball.py)                   │
   │                                                              │
   │  IDENTIFICATION: resolve seeds  (paper / keyword)            │
   │        │                                                     │
   │        ▼                                                     │
   │  fit RelevanceScorer on seeds                                │
   │        │                                                     │
   │        ▼                                                     │
   │  SCREENING  →  ELIGIBILITY  (the BFS loop)                  │
   │  ┌──────────────────────────────────────────────────┐        │
   │  │  round r = 1 .. max_iterations                   │        │
   │  │   │                                              │        │
   │  │   ▼                                              │        │
   │  │  for paper in queue:                              │        │
   │  │   adapters → backward()  (refs)                   │        │
   │  │   adapters → forward()   (cites)                  │        │
   │  │   merge into corpus + add directed edges          │        │
   │  │   │                                              │        │
   │  │   ▼                                              │        │
   │  │  hydrate DOI-only titles (OpenAlex batch 50)      │        │
   │  │   │                                              │        │
   │  │   ▼                                              │        │
   │  │  score new papers; drop < min_relevance           │        │
   │  │   │                                              │        │
   │  │   ▼                                              │        │
   │  │  if kept > per_round_cap → keep top-N, mark rest  │        │
   │  │   │                                              │        │
   │  │   ▼                                              │        │
   │  │  if kept <= saturation_threshold → stop          │        │
   │  │   else queue = kept; loop                         │        │
   │  └──────────────────────────────────────────────────┘        │
   │        │                                                     │
   │        ▼                                                     │
   │  INCLUDED: lazy-fill abstracts from OpenAlex                 │
   │        │                                                     │
   │        ▼                                                     │
   │  persist Run to SQLite; emit final snapshot                  │
   └──────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
                  ┌────────────────────────────────────┐
                  │      USER  (browser, SPA)           │
                  │  graph / list / tree / table         │
                  │  export JSON / CSV / RIS / BibTeX    │
                  └─────────────────────────────────────┘
```

Each "adapters → backward / forward" arrow in the diagram fans out to all
enabled adapters (OpenAlex, Semantic Scholar, Crossref, OpenCitations,
optionally Scholar). Every adapter in turn goes through the shared
`RateLimiter`, which is what keeps the run from being blocked — see
[anti-block.md](anti-block.md).

---

## 8. Plain-English analogies

If you are not from an academic / IR background:

- **Seed papers** are like the seed crystals you drop into a supersaturated
  solution: they give the rest of the run a "shape" to grow around.
- **Backward snowballing** is looking at a book's bibliography — "what
  did the author read?"
- **Forward snowballing** is using a "who-cited-this" service like Google
  Scholar's "Cited by" link — "what came after?"
- **The BFS queue** is exactly what your mail carrier does: deliver to
  every house on this street before moving to the next street, rather than
  following one chain of letters across town.
- **The per-round cap** is the bouncer at a popular club: lots of people
  want in (the long tail of low-relevance hits), but only the top-N most
  relevant get past the velvet rope this round. The rest are still on
  the list — they just don't get to bring their own friends next round.
- **Saturation** is when you keep turning the crank and nothing new comes
  out — time to stop.
- **Abstract hydration** is the courtesy car wash at the end: every paper
  that made the cut gets a final shine before you take it home.

---

## 9. Further reading

- The methodology and PRISMA mapping are cited in
  [references.md](references.md).
- The module-by-module internals are in
  [architecture.md](architecture.md).
- The relevance score is broken down term-by-term in
  [relevance.md](relevance.md).
- The anti-block safeguards are documented in
  [anti-block.md](anti-block.md).
