# CuteySnowball's Anti-Block Strategy

This document explains how CuteySnowball avoids being IP-banned, and
exactly what the user should set if they want to enable the optional
Google Scholar enrichment without getting blocked.

---

## 1. Why the four free APIs are safe by default

Out of the box, CuteySnowball has **four enabled data sources**:

| Source | Auth | Rate limit | Block risk |
|---|---|---|---|
| **OpenAlex** | none (mailto polite) | 100k/day soft | none |
| **Semantic Scholar** | none | 100 req / 5 min anon | none (429 on burst, auto-handled) |
| **Crossref** | none (mailto polite) | 50 req/s polite pool | none |
| **OpenCitations** | none | generous | none |

These four are open, key-less, scholarly infrastructure run by
non-profits (OpenAlex by OurResearch, Semantic Scholar by the Allen
Institute for AI, Crossref by the publishers' consortium, OpenCitations
by the OpenCitations Consortium at the University of Bologna). Their
service model is explicitly "be nice and you won't be blocked" — they
throttle by HTTP 429 with a `Retry-After` header, they don't ban IPs.

For OpenAlex and Crossref the *only* thing they ask is a `mailto`
parameter pointing at a real email you monitor, so they can contact you
if your traffic is misbehaving. CuteySnowball sends this on every request
(configured via `CUTESNOWBALL_MAILTO`).

In short: **with the default config, your IP is never at risk.** You
should still set `CUTESNOWBALL_MAILTO=your-real@example.org` because
that is what the polite pools ask for, but you will not get banned.

---

## 2. The per-host `RateLimiter`

Every external HTTP call in CuteySnowball goes through one object:
`rate_limiter` (a singleton instance of `RateLimiter` in
`cutesnowball/rate_limiter.py`). It is the single most important
anti-block safeguard — by routing every call through here, no host ever
gets hammered.

The limiter keeps one **`_HostBucket` per hostname** (so OpenAlex and
Crossref are throttled independently; one slow host doesn't stall the
other). Each bucket has:

- `min_delay` — minimum seconds between requests to this host (default
  `0.6s`, set by `CUTESNOWBALL_MIN_DELAY`).
- `jitter` — random extra seconds added to every delay (default `0..0.5s`,
  set by `CUTESNOWBALL_JITTER`) so traffic looks human, not metronomic.
- `lock` — thread-safe so two adapters hitting the same host are
  serialised.
- `last_request` — the monotonic timestamp of the last successful call.

The flow inside `RateLimiter.get(url, ...)` is:

1. Look up / lazily create the bucket for the URL's host.
2. `_wait(bucket)`: compute `delay = min_delay + uniform(0, jitter)`;
   if `now - last_request < delay`, sleep the difference; then update
   `last_request`.
3. Send the GET with the project's User-Agent
   (`CuteySnowball/0.1 (mailto:your-real@example.org)`).
4. Inspect the response:
   - **HTTP 429 (Too Many Requests):** read `Retry-After`, cap it at
     **5 seconds** (`wait = min(retry_after, 5.0)`), add 0..1s jitter,
     sleep, retry. **Fail-fast** on the second 429 — return the status
     and let the caller move on to the next adapter.
   - **HTTP 5xx:** linear backoff (`1.0 * (attempt+1)` seconds), retry
     up to `max_retries` (default 3).
   - **Network error** (`requests.RequestException`): linear backoff
     (`1.5 * (attempt+1) + uniform(0, 1)`), retry up to `max_retries`.
   - **2xx / 4xx (non-429):** return immediately. The caller inspects the
     status code; the limiter never raises on HTTP status.

### Why the 5-second cap on `Retry-After`?

Some services (notably OpenAlex's free tier) return a `Retry-After` equal
to **seconds-until-midnight-reset** — values up to 86 400 seconds.
Honouring that literally would hang the snowball run for up to 24 hours
on a single request. CuteySnowball is a snowballing tool, not a
background job: it bails out fast (≤ 5s + jitter) and lets the caller
fall back to the next source. Almost everything CuteySnowball asks for
is available from at least two of the four free APIs, so a single 429
just means "use the other source for this paper".

### Why per-host, not global?

Because OpenAlex (free, generous, 100k/day) and Semantic Scholar
(free, 100 req/5min) are independently safe. A global limiter would
throttle the safe APIs while waiting out a polite Crossref gap. Per-host
means each host is throttled only against itself, so enabling all four
free APIs never causes a flood and never slows down the safe ones.

---

## 3. The Scholar-specific strict floor (8s + 6s jitter)

When the limiter creates a bucket for a `scholar.google.*` host, it
overrides the defaults:

```python
# rate_limiter.py, _bucket()
if "scholar.google" in host:
    b.min_delay = max(8.0, config.min_delay_per_host * 10)  # 8s floor
    b.jitter = 6.0                                          # 6s jitter
else:
    b.min_delay = config.min_delay_per_host
    b.jitter = config.jitter
```

So Scholar requests wait **8 to 14 seconds** between hits, even if the
user set `CUTESNOWBALL_MIN_DELAY=0`. This is roughly **10× stricter**
than the free APIs. Why? Because Google Scholar has no published API
quotas, no `mailto` polite pool, and aggressively bans IPs that issue
many `search_pubs` / `citedby` queries. The 8s floor is the minimum the
`scholarly` project itself recommends.

This is enforced at the limiter level (not at the adapter level), so it
applies equally to the `scholarly` adapter (which uses the `scholarly`
package's HTTP) and the `scholar_scrape` adapter (which uses headless
Chrome). For the `scholar_scrape` adapter there is an *additional*
random delay of `uniform(2, 6)` between page loads in the browser,
stricter than the upstream `scrape-google-scholar-py` project's 1-3s.

---

## 4. The scholarly FreeProxies / ScraperAPI integration

For the `scholarly` adapter, CuteySnowball never lets a request leave
from your real IP. On first use, `_init_scholarly()` builds a
`ProxyGenerator` and configures it according to
`CUTESNOWBALL_SCHOLAR_PROXY`:

- **`free` (default):** `pg.FreeProxies(timeout=1.5, wait_time=180)` —
  rotate through the public list of free HTTPS proxies. `scholarly.use_proxy(pg, pg)`
  routes **both** the outgoing request and the proxy-discovery itself
  through proxies. Your local IP is never exposed to Google Scholar.
  Trade-off: free proxies are slow and unreliable; expect ~50% of
  requests to time out.
- **`scraperapi`:** if you have a ScraperAPI key, set
  `CUTESNOWBALL_SCHOLAR_PROXY=scraperapi` and
  `CUTESNOWBALL_SCRAPERAPI_KEY=your-key`. `pg.ScraperAPI(key)` routes
  every request through ScraperAPI's residential proxy pool with
  automatic CAPTCHA solving and retry. Paid, but rock-solid.
- **`none`:** no proxy. The `scholarly` package will use your local IP.
  **Only do this if you know what you are doing** — Scholar bans are
  typically 24+ hours.

Then `scholarly.set_timeout(15)` (or 60 for ScraperAPI) and
`scholarly.set_retries(5)`. The init runs once and is cached in the
module-level `_INITIALIZED` flag.

---

## 5. CAPTCHA / DOS detection and how the run aborts

Both Scholar adapters detect blocks and raise rather than hammering
through:

- **`scholarly` adapter:** catches `MaxTriesExceededException` (the
  proxies are exhausted — pause for ≥ 1 hour) and `DOSException`
  (Scholar has flagged this as a Denial-of-Service attack — pause for
  ≥ 24 hours) and **re-raises**. The snowball orchestrator catches the
  exception, marks the run as `error`, emits an SSE `error` event, and
  stops. The user can re-run later.
- **`scholar_scrape` adapter:** after every page load, checks the HTML
  for `"unusual traffic"`, `"recaptcha"`, `"gs_captcha_c"`, or
  `"captcha"`. If found, raises `RuntimeError("scholar_scrape: CAPTCHA/block detected")`.
  Same handling at the orchestrator level — the run aborts cleanly.

In both cases the four free APIs continue to work; only the Scholar
adapter bails. The orchestrator's exception handler is in
`Snowballer.run_snowball()`:

```python
try:
    if self.run.mode == "keyword":
        self._do_keyword_mode()
    else:
        self._do_paper_mode()
    self.run.status = "done"
    ...
except Exception as exc:
    self.run.status = "error"
    self.run.error = str(exc)
    _emit(self.cb, phase="error", msg=f"Error: {exc}")
finally:
    self.run.finished_at = time.time()
    save_run(self.run)
```

The `finally` clause always persists the run, so a CAPTCHA mid-run does
not lose the work done up to that point — the corpus, edges, and stats
are all saved in SQLite and visible in the UI.

---

## 6. What to set for safe long-running scholarly use

If you want to use the Google Scholar enrichment for a long batch (e.g.
walking the citations of 50 seed papers), set these in your environment:

```bash
# 1. Always set a real mailto (for the free APIs' polite pool)
export CUTESNOWBALL_MAILTO=you@real-email.org

# 2. Enable scholarly (the more mature of the two Scholar backends)
export CUTESNOWBALL_ENABLE_SCHOLARLY=1

# 3. Use a real proxy — never "none"
#    Option A: ScraperAPI (paid, no blocks, ~$50 for a healthy batch)
export CUTESNOWBALL_SCHOLAR_PROXY=scraperapi
export CUTESNOWBALL_SCRAPERAPI_KEY=your-key-here

#    Option B: FreeProxies (free, slow, ~50% failure rate)
# export CUTESNOWBALL_SCHOLAR_PROXY=free

# 4. (Optional) tighten the rate limit further
export CUTESNOWBALL_MIN_DELAY=1.0    # default 0.6 — bump for caution
export CUTESNOWBALL_JITTER=1.0       # default 0.5

# 5. (Optional) cap the run size so a single run never gets out of hand
export CUTESNOWBALL_MAX_ITERATIONS=3   # default 5 — fewer rounds = less exposure
```

A few practical notes:

- **Don't enable both `scholarly` and `scholar_scrape` at once.** They
  hit the same host (`scholar.google.com`) from the same IP — doubling
  the rate-limiter bucket doesn't help.
- **Run at off-peak hours** if you can. Scholar's CAPTCHA heuristics
  are stricter during the day in the US/EU workday.
- **Expect intermittent CAPTCHAs even with proxies.** Scholar's
  detection is heuristic, not deterministic. The run aborts cleanly when
  it sees one — restart later, or set up a cron that retries.
- **If you only need the four free APIs, do nothing.** The default
  config is safe by design.

---

## 7. Per-host behaviour table

This is the authoritative summary of how `RateLimiter` treats each host
it ever talks to:

| Host pattern | Adapter(s) | min_delay | jitter | On 429 | On 5xx | On net error | Notes |
|---|---|---|---|---|---|---|---|
| `api.openalex.org` | OpenAlexAdapter | 0.6s | 0..0.5s | sleep ≤5s+jitter, retry once; fail-fast on 2nd | linear backoff ×3 | linear backoff ×3 | Polite-pool `mailto` on every call. No ban risk. |
| `api.semanticscholar.org` | SemanticScholarAdapter | 0.6s | 0..0.5s | same | same | same | 100 req/5 min anonymous; 429s are common but auto-handled. |
| `api.crossref.org` | CrossrefAdapter | 0.6s | 0..0.5s | same | same | same | Polite-pool `mailto`; 50 req/s ceiling. |
| `api.opencitations.net` | OpenCitationsAdapter | 0.6s | 0..0.5s | same | same | same | Generous; rarely throttles. |
| `scholar.google.com` (via `scholarly`) | ScholarlyAdapter | **8.0s** | **0..6.0s** | n/a — scholarly handles internally | n/a | n/a — scholarly retries 5× | Routes via FreeProxies / ScraperAPI; raises `MaxTriesExceededException` / `DOSException` → run aborts. |
| `scholar.google.com` (via selenium) | ScholarScrapeAdapter | **8.0s** | **0..6.0s** | n/a — page-level detection | n/a | n/a | Plus an extra `uniform(2, 6)` between page loads. CAPTCHA / "unusual traffic" → `RuntimeError` → run aborts. |

A few invariants that hold for every row:

- **No host is ever hit by two adapters simultaneously from the same IP.**
  The bucket's `lock` serialises them.
- **No host is ever hit more than once per `min_delay` window.** Even if
  the orchestrator schedules 10 calls to OpenAlex in the same round,
  they queue up at the bucket and the gap is enforced.
- **`Retry-After` is never honoured literally if it exceeds 5s.** This
  is what prevents CuteySnowball from hanging for hours on a single
  request to an OpenAlex free tier at 23:59.
- **Network errors never crash the run.** They are retried up to
  `max_retries` (default 3) with linear backoff, then the caller gets a
  `(0, b"", None)` tuple and moves on to the next adapter.

---

## 8. TL;DR for the cautious user

If you are unsure, do this:

1. **Use only the four free APIs.** (This is the default — do nothing.)
2. **Set `CUTESNOWBALL_MAILTO=your-real@example.org`.** (One line.)
3. **Leave the Scholar toggles off.** (`CUTESNOWBALL_ENABLE_SCHOLARLY=0`,
   `CUTESNOWBALL_ENABLE_SCHOLAR_SCRAPE=0` — both are the defaults.)

You will get a fully functional snowballing run on OpenAlex + Semantic
Scholar + Crossref + OpenCitations, with **zero IP-block risk**.

Only turn on Scholar if you have a real proxy (ScraperAPI key recommended)
and you are willing to baby-sit CAPTCHAs. The four free APIs cover > 95%
of real-world SLR/SMS use.
