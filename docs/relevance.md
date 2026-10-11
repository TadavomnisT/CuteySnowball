# How the Relevance Score Works

This document explains exactly how CuteySnowball decides which papers
are "relevant enough" to keep walking, and which to drop. The scorer is
pure-Python — no scikit-learn, no torch, no embeddings — so it runs
anywhere and is fully auditable.

---

## 1. The formula

For any candidate paper `c` discovered during the snowball, the score is
a weighted sum of four terms:

```
relevance(c) = 0.45 * cos_tfidf(seed_corpus, c)
             + 0.25 * jaccard(seed_keywords, c_keywords)
             + 0.15 * recency(c.year)
             + 0.15 * norm_cite(c.num_citations)
```

All four terms are normalised to the `[0, 1]` range, so the final score
is also in `[0, 1]`. The implementation is in
`cutesnowball/relevance.py`, class `RelevanceScorer`, method `.score()`.

The four weights (`0.45`, `0.25`, `0.15`, `0.15`) live in
`cutesnowball/config.py`:

```python
w_tfidf: float = 0.45
w_keyword: float = 0.25
w_recency: float = 0.15
w_citations: float = 0.15
```

They sum to exactly `1.0`. To change them, edit those fields (or
subclass `Config`).

---

## 2. Tokenization

Before any term is computed, every text field (title, abstract, the
keyword query) is tokenised with `tokenize(text)` in `relevance.py`:

- Lower-case the whole string.
- Match against the regex `[a-z0-9][a-z0-9\-]{2,}` — that is, an
  alphanumeric character followed by **two or more** alphanumerics or
  hyphens. So tokens must be at least **3 characters** long. (This
  naturally drops `in`, `of`, `to`, etc.)
- Drop a small built-in English stoplist (`a`, `the`, `for`, `with`,
  `and`, `or`, `but`, `not`, `is`, `are`, `was`, `were`, `be`, `been`,
  `by`, `this`, `that`, `these`, `those`, `it`, `as`, `at`, `from`,
  `which`, `their`, `its`, `his`, `her`, `our`, `your`, `we`, `they`,
  `you`, `i`, `he`, `she`, `them`, `us`, `my`, `into`, `over`, `under`,
  `between`, `among`, `than`, `then`, `so`, `such`, `only`, `also`,
  `more`, `most`, `some`, `any`, `all`, `can`, `could`, `may`, `might`,
  `must`, `should`, `would`, `will`, `shall`, `do`, `does`, `did`,
  `done`, `has`, `have`, `had`, `having`, `about`, `above`, `after`,
  `again`, `against`, `because`, `before`, `below`, `during`, `each`,
  `few`, `here`, `how`, `itself`, `no`, `nor`, `now`, `off`, `other`,
  `out`, `own`, `same`, `there`, `what`, `when`, `where`, `who`, `whom`,
  `why`, `via`, `using`, `based`, `per`, `etc`).
- No stemming, no lemmatisation, no bigrams — by design, to keep the
  scorer simple and debuggable.

Result: a list of clean lowercase tokens like
`["microservices", "performance", "benchmarking", "cloud", "environments"]`.

---

## 3. The TfidfModel

The TF-IDF model is fit **once per run** on the seed corpus (the seed
papers' titles + abstracts). It is implemented from scratch in
`relevance.py`, class `TfidfModel`.

### 3.1 Fitting (`TfidfModel.fit(seeds)`)

1. Tokenise each seed: `docs = [tokenize(title + " " + abstract) for p in seeds]`.
2. Build the document-frequency table: `df[w] = number of docs containing w`.
3. Build the vocabulary: `vocab = {word: index}` sorted alphabetically.
4. Compute the inverse document frequency for each word:
   `idf[w] = log((1 + n) / (1 + df[w])) + 1.0`, where `n = len(seeds)`.
   The `+ 1` inside `log` and the `+ 1.0` outside are both
   [sklearn-style smoothing](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfTransformer.html)
   so we never divide by zero on a corpus of one.
5. Compute the TF-IDF vector for each seed doc:
   `vec[idx] = (1 + log(count)) * idf[idx]` (sublinear TF).
6. Compute the **average seed vector** — element-wise mean of all seed
   vectors. This is the single vector that represents the "centre" of
   the seed set.
7. Cache the average vector and its L2 norm.

### 3.2 Scoring (`TfidfModel.cosine_vs_seed(text)`)

1. Tokenise the candidate text.
2. Compute its TF-IDF vector (same sublinear-TF formula).
3. Compute its L2 norm.
4. Compute the dot product with the average seed vector (iterating the
   smaller of the two dicts for speed — long abstracts rarely share
   more than a few dozen words with the seed corpus).
5. Return `dot / (cand_norm * avg_norm)` — standard cosine similarity.

For papers whose text shares no tokens with the seed corpus, the
cosine is `0.0` and only the other three terms contribute.

---

## 4. The keyword Jaccard

For a paper `p`, `keywords_of(p)` builds a **set** of tokens from
`(p.title + " ") * 3 + p.abstract` — that is, the title repeated **three
times** (so title words dominate the set) followed by the abstract. The
result is a Python `set`, so each word appears at most once.

The seed keyword set is the **union** of `keywords_of(seed)` over all
seeds.

The Jaccard similarity is:

```
jaccard(A, B) = |A ∩ B| / |A ∪ B|
              = |intersection| / (|A| + |B| - |intersection|)
```

So if the seed set has 10 keywords and the candidate has 5, of which 3
overlap, the Jaccard is `3 / (10 + 5 - 3) = 3/12 = 0.25`.

The 3x title weighting is why a candidate with a matching **title**
keyword scores much higher than one that merely mentions the keyword in
the abstract body.

---

## 5. Recency

The recency term rewards newer papers, with diminishing returns:

```
recency(year) = 1 - exp(-(year - ref_year) / tau)
```

with `ref_year = 2000` and `tau = 10` by default (both in `config.py`).

A few reference points (with `ref_year=2000, tau=10`):

| Year | recency |
|---|---|
| 2000 | `1 - exp(0) = 0.000` |
| 2005 | `1 - exp(-0.5) ≈ 0.393` |
| 2010 | `1 - exp(-1.0) ≈ 0.632` |
| 2015 | `1 - exp(-1.5) ≈ 0.777` |
| 2020 | `1 - exp(-2.0) ≈ 0.865` |
| 2024 | `1 - exp(-2.4) ≈ 0.909` |
| 2030 | `1 - exp(-3.0) ≈ 0.950` |

So a 2024 paper gets ~0.91 recency points, a 2010 paper gets ~0.63, and
a 2000 paper gets 0. The curve is exponential — older papers aren't
penalised to zero, but they don't dominate either.

If `year` is `None` (unknown — happens with some Crossref unstructured
citations), recency is `0.0`.

---

## 6. Citation count normalisation

The citation term is `log1p`-saturated to avoid a single mega-paper
(50 000 citations) drowning out everything else:

```
norm_cite(n) = min(1.0, log1p(n) / log1p(1000))
            = min(1.0, ln(n+1) / ln(1001))
```

A few reference points:

| `num_citations` | `log1p(n)` | `norm_cite` |
|---|---|---|
| 0 | 0.000 | 0.000 |
| 5 | 1.792 | 0.259 |
| 10 | 2.398 | 0.347 |
| 30 | 3.434 | 0.497 |
| 100 | 4.615 | 0.668 |
| 300 | 5.707 | 0.826 |
| 1000 | 6.909 | 1.000 |
| 10 000 | 9.210 | 1.000 (capped) |
| 50 000 | 10.820 | 1.000 (capped) |

So **a 1 000-cite paper scores the same as a 50 000-cite paper**. The
rationale: in snowballing, citation count is a noisy proxy for
"important" — anything past ~1 000 citations is already clearly
influential, and giving it more weight would just push the corpus toward
a handful of mega-papers (e.g. *Adam: A Method for Stochastic
Optimization*) and away from the seed-specific literature.

---

## 7. Why these weights?

The default weights — **`0.45 / 0.25 / 0.15 / 0.15`** — encode an
intentionally **IR-conservative** blend:

1. **TF-IDF cosine (0.45)** is the heaviest because it captures genuine
   semantic overlap with the seed corpus. A paper that uses the same
   technical vocabulary as your seeds is far more likely to be relevant
   than one that just happens to mention a keyword. This is the dominant
   information-retrieval signal since Salton & Buckley (1988).

2. **Keyword Jaccard (0.25)** is the second-heaviest because it captures
   *exact-match* signal that TF-IDF can miss. TF-IDF with sublinear TF
   and an average seed vector can under-weight rare exact matches
   (e.g. a domain-specific proper noun like "Kubernetes"). Jaccard on
   the title-weighted keyword set is a complementary signal.

3. **Recency (0.15)** is small but non-zero because in fast-moving fields
   (e.g. LLMs, microservices) newer work is genuinely more likely to be
   relevant to a current SLR. The exponential saturation means a 2018
   paper isn't shut out, just slightly down-weighted.

4. **Citations (0.15)** is also small because in snowballing the citation
   count is mostly a *popularity* signal, not a *relevance* signal. A
   50 000-cite survey paper is influential but probably off-topic; a
   30-cite niche paper might be exactly what the SLR needs. The
   log1p saturation at 1 000 prevents the popularity tail from
   dominating.

If you are doing a *historical* review (where recency is irrelevant) you
might lower `w_recency` to 0 and bump `w_tfidf` to 0.60. If you are
doing a *mapping study* (where breadth matters more than depth) you
might lower `w_tfidf` to 0.35 and raise `w_keyword` to 0.35.

---

## 8. Seeds always score ≥ 0.7 in keyword mode

In keyword mode (`mode == "keyword"`), the seeds are the top-N search
results, not user-supplied papers. They were chosen because they scored
highly against the query — but the query itself was just a few keywords,
so the absolute scores can be modest (e.g. 0.35).

If we let the relevance filter (default `min_relevance = 0.18`) act on
these unmodified scores, the seeds themselves would frequently be
filtered out — which is nonsense (a seed should always survive its own
snowball).

To prevent this, `Snowballer._keyword_seeds()` does:

```python
for s in seeds:
    s.seed = True
    s.relevance = max(s.relevance, 0.7)   # seeds are inherently relevant
```

This **clamps** every seed's score to at least `0.7` regardless of what
the scorer computed. It does *not* affect the scoring of any non-seed
paper; it is only applied to the seeds themselves, after they are
picked. In paper mode (`mode == "paper"`), seeds are user-supplied and
score a flat `1.0` (`p.relevance = 1.0` in `_do_paper_mode`).

---

## 9. How to tune

The scorer has two layers of tunables:

### 9.1 Environment variables (already wired up)

These live in `config.py` and are read from the environment on startup:

| Variable | Default | Effect on relevance filtering |
|---|---|---|
| `CUTESNOWBALL_MIN_DELAY` | `0.6` | (anti-block, see [anti-block.md](anti-block.md)) |
| `CUTESNOWBALL_DEBUG` | `0` | Verbose logging |
| — | — | — |

Relevance-specific env vars are limited to **`min_relevance`**,
**`per_round_cap`**, **`max_iterations`**, and **`max_total_papers`**,
which are read from `config.py` but not currently exposed as env vars.
You can change them by editing `config.py` directly.

### 9.2 Editing `config.py` (for weight tuning)

The four weights and the recency parameters are not env-driven — to
change them, edit the `Config` dataclass in
`cutesnowball/config.py`:

```python
w_tfidf: float = 0.45          # raise for stricter semantic match
w_keyword: float = 0.25        # raise for exact-keyword-match sensitivity
w_recency: float = 0.15        # raise for fast-moving fields
w_citations: float = 0.15      # raise for "importance" weighting
recency_ref_year: int = 2000   # the year recency() returns 0 for
recency_tau: float = 10.0      # larger = slower recency growth
```

The four `w_*` weights must sum to `1.0` (or close — they're normalised
internally by being summed implicitly into the score, but skewing them
away from summing to 1 will shift the absolute scores up or down).

### 9.3 Per-run overrides (advanced options)

The `POST /api/run` body accepts an `options` dict that is currently
honoured for `max_iterations`, `min_relevance`, `per_round_cap`, and
`keyword_top_n` (used in `_do_keyword_mode` and `_snowball_loop`). The
weights are read from the singleton `config`, **not** from `options`, so
per-run weight overrides require a small code change in
`Snowballer.__init__`:

```python
self._scorer = RelevanceScorer(seeds, w=options.get("weights"))
```

This is left as an exercise for the user — we recommend keeping the
weights global so runs are comparable across sessions.

---

## 10. A worked example with 2 seeds and 1 candidate

Let's walk through a real calculation.

### Setup

- **Seed 1:** "Microservices performance benchmarking in cloud
  environments", year 2022, 150 citations, no abstract.
- **Seed 2:** "Container orchestration for scalable microservices",
  year 2020, 90 citations, no abstract.
- **Candidate:** "Microservices benchmarking on Kubernetes clusters",
  year 2024, 30 citations, no abstract.

### Step 1 — Tokenize

| Source | Tokens |
|---|---|
| Seed 1 title | `microservices, performance, benchmarking, cloud, environments` (the word "in" is 2 chars and doesn't match the regex) |
| Seed 2 title | `container, orchestration, scalable, microservices` ("for" is a stopword) |
| Candidate title | `microservices, benchmarking, kubernetes, clusters` ("on" is 2 chars) |

### Step 2 — TF-IDF fit on the seeds

Vocabulary (sorted) and idf (n = 2 docs):

| Word | df | idf = ln((1+2)/(1+df)) + 1 |
|---|---|---|
| benchmarking | 1 | ln(3/2)+1 ≈ 1.405 |
| cloud | 1 | 1.405 |
| container | 1 | 1.405 |
| environments | 1 | 1.405 |
| microservices | 2 | ln(3/3)+1 = 1.000 |
| orchestration | 1 | 1.405 |
| performance | 1 | 1.405 |
| scalable | 1 | 1.405 |

Average seed vector (mean of seed 1 and seed 2 vectors):

| Word | Seed 1 vec | Seed 2 vec | Average |
|---|---|---|---|
| benchmarking | 1.405 | 0 | 0.7025 |
| cloud | 1.405 | 0 | 0.7025 |
| container | 0 | 1.405 | 0.7025 |
| environments | 1.405 | 0 | 0.7025 |
| microservices | 1.000 | 1.000 | 1.0000 |
| orchestration | 0 | 1.405 | 0.7025 |
| performance | 1.405 | 0 | 0.7025 |
| scalable | 0 | 1.405 | 0.7025 |

(Each `vec[word] = (1 + ln(1)) * idf = idf` since each word appears
exactly once in the docs that contain it.)

`avg_norm = sqrt(1.0² + 7 × 0.7025²) = sqrt(1 + 3.454) = sqrt(4.454) ≈ 2.110`

### Step 3 — TF-IDF cosine for the candidate

Candidate's TF-IDF vector (only the words in vocab count;
"kubernetes" and "clusters" are unknown to the model):

| Word | Candidate vec |
|---|---|
| microservices | 1.000 |
| benchmarking | 1.405 |

`cand_norm = sqrt(1.0² + 1.405²) = sqrt(1 + 1.974) = sqrt(2.974) ≈ 1.724`

Dot product with the average seed vector:

```
dot = (1.000 × 1.000)         # microservices
    + (1.405 × 0.7025)        # benchmarking
    = 1.000 + 0.987
    = 1.987
```

```
cos = dot / (cand_norm × avg_norm)
    = 1.987 / (1.724 × 2.110)
    = 1.987 / 3.639
    ≈ 0.546
```

### Step 4 — Keyword Jaccard

`seed_kw` (union of `keywords_of(seed 1)` ∪ `keywords_of(seed 2)`):

```
{microservices, performance, benchmarking, cloud, environments,
 container, orchestration, scalable}     |A| = 8
```

`keywords_of(candidate)` (title repeated 3× — the title-weighting —
but as a set, so duplicates collapse):

```
{microservices, benchmarking, kubernetes, clusters}     |B| = 4
```

Intersection: `{microservices, benchmarking}` → `|A ∩ B| = 2`

```
jaccard = |A ∩ B| / |A ∪ B|
        = 2 / (8 + 4 - 2)
        = 2 / 10
        = 0.200
```

### Step 5 — Recency

```
recency(2024) = 1 - exp(-(2024 - 2000) / 10)
             = 1 - exp(-2.4)
             = 1 - 0.0907
             ≈ 0.909
```

### Step 6 — Citation normalisation

```
norm_cite(30) = min(1.0, log1p(30) / log1p(1000))
             = min(1.0, ln(31) / ln(1001))
             = min(1.0, 3.434 / 6.908)
             ≈ 0.497
```

### Step 7 — Final score

```
relevance = 0.45 × 0.546      (TF-IDF)
          + 0.25 × 0.200      (keyword Jaccard)
          + 0.15 × 0.909      (recency)
          + 0.15 × 0.497      (citations)

          = 0.2457 + 0.0500 + 0.1364 + 0.0746
          = 0.5067
```

So the candidate paper **"Microservices benchmarking on Kubernetes
clusters"** scores **0.507** against the seed set, comfortably above
the default `min_relevance = 0.18`, so it would be kept and walked in
the next round.

### ASCII summary

```
            TF-IDF cosine ────────►   0.546   × 0.45 =  0.2457
            keyword Jaccard ───────►  0.200   × 0.25 =  0.0500
            recency(2024) ────────►  0.909   × 0.15 =  0.1364
            norm_cite(30) ────────►  0.497   × 0.15 =  0.0746
            ───────────────────────────────────────────────────
            relevance(candidate)                          0.5067
```

The breakdown also shows *why* the candidate scored well: it shares two
title tokens with the seed corpus (`microservices`, `benchmarking`),
it's recent (2024 → 0.909), and it has a modest citation count (30 →
0.497, well below the 1 000 saturation cap). If the user lowered
`w_recency` to 0 (e.g. for a historical review), the score would drop to
`0.2457 + 0.0500 + 0 + 0.0746 = 0.3703` — still above the threshold, but
the recency boost was worth ~0.14 in this case.

---

## 11. Caveats and known limits

- **The score is a heuristic**, not a gold standard. Wohlin (2014)
  explicitly prescribes *qualitative* inclusion in snowballing, not a
  numeric threshold. Treat the score as a **ranking aid** — sort the
  corpus by it, but read the abstracts before final inclusion decisions.
- **No semantic embeddings.** Two papers can be topically identical
  with no shared tokens (e.g. "microservices" vs "µservices") and the
  TF-IDF term will be 0. This is the price of having no torch
  dependency.
- **Single-language stoplist.** The stoplist is English-only. Non-English
  corpora will need a small code change.
- **No bigrams.** "machine learning" is two tokens, not one. For most
  SLR work this is fine; for highly technical vocabularies (where
  "convolutional neural" is different from "convolutional" + "neural")
  you'd want to add bigram support in `tokenize()`.
- **Citation counts vary by source.** OpenAlex, Semantic Scholar, and
  Crossref can disagree by 10-30%. The `merge()` step keeps the max
  across sources, so the citation term is "best-seen" rather than
  canonical.
