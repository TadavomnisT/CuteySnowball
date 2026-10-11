"""PDF reference extraction (pure-Python, no external CDN).

Ported from the BackwardForwardSnowballing project's `js/pdf.js`:
  * extract text via pypdf
  * detect the "References" / "Bibliography" section
  * split into individual references (numbered [1] / APA styles)
  * parse each ref into {title, authors, year, doi}

pypdf is the only PDF dependency and is pure-Python (no native code), so
this works in any environment.  For scanned/image PDFs there is no text
layer and we return [] (same limitation as the upstream JS tool, which
uses Mozilla pdf.js).
"""
from __future__ import annotations

import io
import re
from typing import List, Optional, Tuple

from .models import Paper

try:
    from pypdf import PdfReader  # type: ignore

    _PYPDF_AVAILABLE = True
except Exception:  # pragma: no cover
    _PYPDF_AVAILABLE = False

# Reference-section heading (anchored on its own line).
_REF_HEADING_RE = re.compile(
    r"^\s*(References|REFERENCES|Bibliography|BIBLIOGRAPHY|Références|"
    r"Works Cited|Literature Cited)\s*$",
    re.MULTILINE,
)
# Cut at the first appendix/supplementary/acknowledgement line.
_END_RE = re.compile(
    r"^\s*(Appendix|APPENDIX|Supplementary|Acknowledg(e)?ments?|Author Bio)\b",
    re.MULTILINE,
)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;}\]\)]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\((\d{4})\)|(?<=[\s,;])(\d{4})(?=[;:,.\s]|$)")
_NUMBERED_RE = re.compile(
    r"(?:^|\n)\s*(?:\[?\d{1,3}\]?[\.\):]|\(\d{1,3}\))\s+"
)
_HYPHEN_RE = re.compile(r"-\s*\n\s*([a-z])")


def extract_text_from_pdf(data: bytes) -> str:
    if not _PYPDF_AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(out)


def _split_numbered(text: str) -> List[str]:
    parts = _NUMBERED_RE.split(text)
    # split keeps the delimiters; rebuild
    out = []
    cur = ""
    for part in parts:
        if _NUMBERED_RE.fullmatch(part):
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += part
    if cur.strip():
        out.append(cur.strip())
    return out


def _is_apa_start(line: str) -> bool:
    # APA refs start with Surname, Initials. then a year in parens-ish.
    return bool(re.match(r"^[A-Z][a-zA-Z\-']+,?\s*[A-Z]", line))


def _split_apa(text: str) -> List[str]:
    lines = [l for l in text.splitlines() if l.strip()]
    out = []
    cur = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if cur and _is_apa_start(line):
            out.append(_HYPHEN_RE.sub(r"\1", cur).strip())
            cur = line
        else:
            cur = (" " if cur else "") + line
    if cur.strip():
        out.append(_HYPHEN_RE.sub(r"\1", cur).strip())
    return out


def _parse_one(ref: str) -> Optional[Paper]:
    if len(ref) < 25:
        return None
    ref = ref.strip()
    # strip leading number
    ref = re.sub(r"^\s*\[?\d{1,3}\]?[\.\):]?\s*", "", ref)
    doi_m = _DOI_RE.search(ref)
    doi = doi_m.group(1).lower().rstrip(".,;)]}") if doi_m else None
    year_m = _YEAR_RE.search(ref[:140])
    year = None
    if year_m:
        for g in year_m.groups():
            if g:
                try:
                    year = int(g)
                    break
                except ValueError:
                    continue
    # crude title extraction
    title = ref
    if year_m:
        title = ref[: year_m.start()].rstrip(" .,;")
    # Vancouver: split at first colon
    if ":" in title[:80]:
        title = title.split(":", 1)[1]
    title = title.strip(" .,;\"'")[:300]
    if len(title) < 8:
        title = ref[:80].strip()
    # authors = text before title
    authors = ref[: ref.find(title)].strip(" .,;")[:300] if title in ref else ""
    return Paper(
        title=title,
        doi=doi,
        authors=authors,
        year=year,
        sources=["pdf"],
        raw=ref,
    )


def extract_references_from_pdf(data: bytes) -> Tuple[Optional[str], List[Paper]]:
    """Return (doi_of_first_page, list_of_references).

    doi_of_first_page is extracted from the concatenated text of the first
    page (matches BackwardForwardSnowballing's behaviour).
    """
    text = extract_text_from_pdf(data)
    if not text:
        return None, []
    # DOI on the whole text (first occurrence is usually the paper's own DOI)
    first_doi = None
    m = _DOI_RE.search(text[:8000])
    if m:
        first_doi = m.group(1).lower().rstrip(".,;)]}")
    # Find reference section
    matches = list(_REF_HEADING_RE.finditer(text))
    start = matches[-1].end() if matches else int(0.7 * len(text))
    body = text[start:]
    end_m = _END_RE.search(body)
    if end_m:
        body = body[: end_m.start()]
    # try both splitters, pick the longer (>=3 entries)
    num = _split_numbered(body)
    apa = _split_apa(body)
    chosen = num if len(num) >= max(3, len(apa)) else apa
    out: List[Paper] = []
    for raw in chosen:
        p = _parse_one(raw)
        if p and (len(p.raw) >= 25 or p.doi or p.year):
            out.append(p)
    # dedup by raw text
    seen = set()
    dedup = []
    for p in out:
        k = (p.raw or p.title or "").lower().strip()[:120]
        if k and k in seen:
            continue
        seen.add(k)
        dedup.append(p)
    return first_doi, dedup
