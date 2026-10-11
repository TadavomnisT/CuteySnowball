"""Port of scrape-google-scholar-py (dimitryzub/scrape-google-scholar-py).

This is a SECONDARY enrichment source.  OFF by default.  Uses the
selenium-stealth CSS selectors from the upstream project to scrape Google
Scholar's organic SERP.  We use it as a search fallback when OpenAlex /
Semantic Scholar / Crossref return too few results for a keyword query,
and as an alternate forward-snowballing source (via the "Cited by" link).

The selectors below are quoted verbatim (or near-verbatim) from
google_scholar_py/custom_backend/organic_search.py and are the most
important reusable artefact of that project.

Anti-block:
  * ONE headless Chrome session per adapter instance, reused.
  * random.uniform(2, 6) between page loads (stricter than upstream's 1-3s).
  * On CAPTCHA / "unusual traffic" -> raise, so the orchestrator pauses.
  * Never the primary source; only used when the user explicitly enables it.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import List, Optional

from ..config import config
from ..models import Paper
from .base import CitationAdapter

log = logging.getLogger("cutesnowball.scrape")

try:
    from selenium import webdriver  # type: ignore
    from selenium.webdriver.chrome.service import Service  # type: ignore
    from selenium.webdriver.chrome.options import Options  # type: ignore
    from selenium.common.exceptions import TimeoutException, WebDriverException  # type: ignore

    _SELENIUM_AVAILABLE = True
except Exception:  # pragma: no cover - optional dep
    _SELENIUM_AVAILABLE = False

try:
    from selectolax.lexbor import LexborHTMLParser  # type: ignore

    _SELECTOLAX_AVAILABLE = True
except Exception:
    try:
        from bs4 import BeautifulSoup  # type: ignore

        _SELECTOLAX_AVAILABLE = False
    except Exception:
        _SELECTOLAX_AVAILABLE = False

try:
    from selenium_stealth import stealth  # type: ignore
    _STEALTH_AVAILABLE = True
except Exception:
    _STEALTH_AVAILABLE = False

try:
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
    _WDM_AVAILABLE = True
except Exception:
    _WDM_AVAILABLE = False


SCHOLAR_URL = "https://scholar.google.com/scholar?q={q}&hl=en&gl=us&start={start}"


def _parse(html: str) -> List[Paper]:
    """Parse a Google Scholar organic SERP into Papers.

    Selectors ported from scrape-google-scholar-py/organic_search.py:
      result container : .gs_r.gs_or.gs_scl
      title            : .gs_rt
      title link       : .gs_rt a
      publication info: .gs_a
      snippet          : .gs_rs
      cited-by link    : .gs_ri .gs_fl a where 'Cited by' in text
      pdf link         : .gs_or_ggsm a
    """
    if _SELECTOLAX_AVAILABLE:
        parser = LexborHTMLParser(html)
        results = parser.css(".gs_r.gs_or.gs_scl")
        rows = []
        for r in results:
            try:
                title_node = r.css_first(".gs_rt")
                title = title_node.text(strip=True) if title_node else ""
                link_node = r.css_first(".gs_rt a")
                link = link_node.attributes.get("href", "") if link_node else ""
                info_node = r.css_first(".gs_a")
                info = info_node.text(strip=True) if info_node else ""
                snippet_node = r.css_first(".gs_rs")
                snippet = snippet_node.text(strip=True) if snippet_node else ""
                cited_by_link = ""
                cited_by_count = 0
                for a in r.css(".gs_ri .gs_fl a"):
                    t = a.text()
                    if "Cited by" in t:
                        cited_by_link = a.attributes.get("href", "")
                        m = re.search(r"\d+", t)
                        if m:
                            try:
                                cited_by_count = int(m.group())
                            except ValueError:
                                pass
                        break
                if cited_by_link and cited_by_link.startswith("/"):
                    cited_by_link = "https://scholar.google.com" + cited_by_link
                pdf_link = ""
                pdf_node = r.css_first(".gs_or_ggsm a")
                if pdf_node:
                    pdf_link = pdf_node.attributes.get("href", "")
                rows.append((title, link, info, snippet, cited_by_link, cited_by_count, pdf_link))
            except Exception:
                continue
    else:
        # BeautifulSoup fallback
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        for r in soup.select(".gs_r.gs_or.gs_scl"):
            try:
                title_node = r.select_one(".gs_rt")
                title = title_node.get_text(strip=True) if title_node else ""
                link_node = r.select_one(".gs_rt a")
                link = link_node.get("href", "") if link_node else ""
                info_node = r.select_one(".gs_a")
                info = info_node.get_text(strip=True) if info_node else ""
                snippet_node = r.select_one(".gs_rs")
                snippet = snippet_node.get_text(strip=True) if snippet_node else ""
                cited_by_link = ""
                cited_by_count = 0
                for a in r.select(".gs_ri .gs_fl a"):
                    t = a.get_text()
                    if "Cited by" in t:
                        cited_by_link = a.get("href", "")
                        m = re.search(r"\d+", t)
                        if m:
                            try:
                                cited_by_count = int(m.group())
                            except ValueError:
                                pass
                        break
                if cited_by_link and cited_by_link.startswith("/"):
                    cited_by_link = "https://scholar.google.com" + cited_by_link
                pdf_link = ""
                pdf_node = r.select_one(".gs_or_ggsm a")
                if pdf_node:
                    pdf_link = pdf_node.get("href", "")
                rows.append((title, link, info, snippet, cited_by_link, cited_by_count, pdf_link))
            except Exception:
                continue

    out: List[Paper] = []
    for title, link, info, snippet, cbl, cbc, pdf in rows:
        if not title:
            continue
        authors, year, venue = "", None, ""
        if info:
            # "A Smith, B Jones - Journal Name, 2020 - publisher"
            parts = [p.strip() for p in info.split(" - ")]
            if parts:
                authors = parts[0]
            if len(parts) >= 2:
                ym = re.search(r"(19|20)\d{2}", parts[1])
                if ym:
                    try:
                        year = int(ym.group())
                    except ValueError:
                        pass
                venue = re.sub(r",?\s*(19|20)\d{2}.*$", "", parts[1]).strip()
        # DOI from link/snippet if present
        doi = None
        m = re.search(r"\b(10\.\d{4,9}/[^\s\"<>&]+)", link + " " + snippet)
        if m:
            doi = m.group(1).lower().rstrip(".,;)]}")
        out.append(
            Paper(
                title=title,
                doi=doi,
                authors=authors,
                year=year,
                abstract=snippet,
                venue=venue,
                num_citations=cbc,
                sources=["scholar_scrape"],
                url=link,
                pdf_url=pdf,
                scholar_id=cbl,
            )
        )
    return out


class ScholarScrapeAdapter(CitationAdapter):
    """Selenium-stealth Google Scholar scraper (port of scrape-google-scholar-py)."""

    name = "scholar_scrape"

    def __init__(self):
        self._driver = None
        self._healthy = _SELENIUM_AVAILABLE and _STEALTH_AVAILABLE and _WDM_AVAILABLE

    # ------------------------------------------------------------------
    def _driver_obj(self):
        if self._driver is not None:
            return self._driver
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        options.add_argument(f"--user-agent={ua}")
        try:
            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)
        except Exception as exc:  # pragma: no cover
            log.warning("Chrome init failed: %s", exc)
            self._driver = webdriver.Chrome(options=options)
        if _STEALTH_AVAILABLE:
            try:
                stealth(
                    self._driver,
                    languages=["en-US", "en"],
                    vendor="Google Inc.",
                    platform="Win32",
                    webgl_vendor="Intel Inc.",
                    renderer="Intel Iris OpenGL Engine",
                    fix_hairline=True,
                )
            except Exception:  # pragma: no cover
                pass
        self._driver.set_page_load_timeout(40)
        return self._driver

    def healthy(self) -> bool:
        return self._healthy

    def _fetch(self, url: str) -> Optional[str]:
        drv = self._driver_obj()
        try:
            drv.get(url)
        except TimeoutException:
            return None
        except WebDriverException as exc:
            log.warning("selenium fetch failed: %s", exc)
            return None
        # CAPTCHA detection
        src = drv.page_source or ""
        low = src.lower()
        if "unusual traffic" in low or "recaptcha" in low or "gs_captcha_c" in low or "captcha" in low:
            log.error("Google Scholar CAPTCHA / block detected")
            raise RuntimeError("scholar_scrape: CAPTCHA/block detected")
        return src

    # ------------------------------------------------------------------
    def resolve(self, doi: Optional[str], title: Optional[str] = None) -> Optional[Paper]:
        q = title or doi
        if not q:
            return None
        url = SCHOLAR_URL.format(q=urllib.parse.quote(q), start=0)
        try:
            html = self._fetch(url)
            if not html:
                return None
            res = _parse(html)
            return res[0] if res else None
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("scholar_scrape resolve failed: %s", exc)
            return None

    def forward(self, paper: Paper) -> List[Paper]:
        """Walk the 'Cited by' link if we have one."""
        if not paper.scholar_id:
            return []
        # scholar_id stores the cited-by URL when populated by search()
        url = paper.scholar_id
        if not url.startswith("http"):
            url = "https://scholar.google.com" + url
        try:
            html = self._fetch(url)
            if not html:
                return []
            return _parse(html)
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("scholar_scrape forward failed: %s", exc)
            return []

    def backward(self, paper: Paper) -> List[Paper]:
        # scrape-google-scholar-py does not implement backward snowballing
        return []

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        url = SCHOLAR_URL.format(q=urllib.parse.quote(query), start=0)
        try:
            html = self._fetch(url)
            if not html:
                return []
            res = _parse(html)
            return res[:limit]
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("scholar_scrape search failed: %s", exc)
            return []

    def close(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
