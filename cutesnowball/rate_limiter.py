"""Per-host polite rate limiter.

Every external HTTP call in CuteySnowball goes through `RateLimiter.get()`
which:
  * sleeps at least `min_delay_per_host` between requests to the same host
  * adds random jitter so the traffic looks human
  * retries on HTTP 429 with exponential backoff
  * retries on transient network errors

This is the single most important anti-block safeguard: by routing every
call through here, no host ever gets hammered, and 429s are respected.

Design note: we deliberately keep this *per-host*, not global, so that
hitting OpenAlex (free, generous) and Semantic Scholar (free, 100 req/s)
in parallel never throttles the safe sources while we wait for the
polite Crossref gap.  Google Scholar (when enabled) gets its own host
bucket which is far stricter because Scholar bans aggressively.
"""
from __future__ import annotations

import random
import threading
import time
import urllib.parse
from typing import Dict, Optional, Tuple

import requests

from .config import config


class _HostBucket:
    __slots__ = ("host", "last_request", "lock", "fails", "min_delay", "jitter")

    def __init__(self, host: str):
        self.host = host
        self.last_request = 0.0
        self.lock = threading.Lock()
        self.fails = 0
        self.min_delay = config.min_delay_per_host
        self.jitter = config.jitter


class RateLimiter:
    """Thread-safe per-host rate limiter + HTTP client."""

    def __init__(self):
        self._buckets: Dict[str, _HostBucket] = {}
        self._global_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": f"CuteySnowball/0.1 (mailto:{config.mailto}; +https://github.com/TadavomnisT/CuteySnowball)"
            }
        )

    # ------------------------------------------------------------------
    def _bucket(self, url: str) -> _HostBucket:
        host = urllib.parse.urlparse(url).netloc.lower()
        with self._global_lock:
            b = self._buckets.get(host)
            if b is None:
                b = _HostBucket(host)
                # Scholar is extra sensitive - long floor delay.
                if "scholar.google" in host:
                    b.min_delay = max(8.0, config.min_delay_per_host * 10)
                    b.jitter = 6.0
                else:
                    b.min_delay = config.min_delay_per_host
                    b.jitter = config.jitter
                self._buckets[host] = b
            return b

    def _wait(self, bucket: _HostBucket):
        with bucket.lock:
            now = time.monotonic()
            elapsed = now - bucket.last_request
            delay = bucket.min_delay + random.uniform(0, bucket.jitter)
            if elapsed < delay:
                time.sleep(delay - elapsed)
            bucket.last_request = time.monotonic()

    # ------------------------------------------------------------------
    def get(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: Optional[float] = None,
        accept: str = "application/json",
    ) -> Tuple[int, bytes, Optional[requests.Response]]:
        """Perform a polite GET.  Returns (status, body_bytes, response).

        Retries on 429 / 5xx with backoff.  Never raises on HTTP status;
        caller inspects the status code.
        """
        bucket = self._bucket(url)
        h = {"Accept": accept}
        if config.mailto:
            h["User-Agent"] = (
                f"CuteySnowball/0.1 (mailto:{config.mailto})"
            )
        if headers:
            h.update(headers)

        last_exc: Optional[Exception] = None
        last_resp: Optional[requests.Response] = None
        for attempt in range(config.max_retries + 1):
            self._wait(bucket)
            try:
                resp = self._session.get(
                    url,
                    params=params,
                    headers=h,
                    timeout=timeout or config.request_timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                bucket.fails += 1
                # network error - backoff and retry
                time.sleep(1.5 * (attempt + 1) + random.uniform(0, 1))
                continue

            last_resp = resp
            if resp.status_code == 429:
                # Fail-fast: respect Retry-After but CAP it at 5s.  Some
                # services (e.g. OpenAlex free tier) return Retry-After
                # = seconds-until-midnight-reset (up to 86400s); honouring
                # that literally would hang the caller for hours.  We are
                # a snowballing tool, not a background job — bail out fast
                # and let the caller move on to the next source.
                if attempt >= 1:
                    bucket.fails += 1
                    return resp.status_code, resp.content, resp
                ra = resp.headers.get("Retry-After")
                wait = 2.0
                if ra and ra.isdigit():
                    wait = min(float(ra), 5.0)
                wait += random.uniform(0, 1)
                time.sleep(wait)
                continue
            if 500 <= resp.status_code < 600 and attempt < config.max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            # success or non-retryable status
            bucket.fails = 0
            return resp.status_code, resp.content, resp

        # exhausted retries
        if last_resp is not None:
            return last_resp.status_code, last_resp.content, last_resp
        # total network failure
        return 0, b"", None

    def get_json(self, url: str, **kw) -> Tuple[int, Optional[dict]]:
        status, body, _ = self.get(url, accept="application/json", **kw)
        if status != 200 or not body:
            return status, None
        try:
            import json
            return status, json.loads(body)
        except Exception:
            return status, None


# Singleton.
rate_limiter = RateLimiter()
