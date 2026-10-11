"""Export utilities: RIS, CSV, JSON, BibTeX, PRISMA flow.

All exporters are pure-Python (no external deps) and write to in-memory
strings so the Flask routes can stream them as downloads.

BibTeX is generated with a minimal hand-rolled encoder so we don't pull
in the (heavy) `bibtexparser` dependency that the upstream `scholarly`
package uses — CuteySnowball keeps its dependency footprint small.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import List

from .models import Paper, Run


def _csv_safe(s: str) -> str:
    return (s or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")


def export_csv(run: Run, include_abstracts: bool = True, only_included: bool = True) -> str:
    buf = io.StringIO()
    buf.write("\ufeff")  # Excel BOM
    cols = [
        "Number",
        "Title",
        "DOI",
        "Authors",
        "Year",
        "Venue",
        "NumCitations",
        "Relevance",
        "Depth",
        "Round",
        "Seed",
        "Included",
        "Sources",
        "URL",
        "Abstract",
        "Annotation",
    ]
    if not include_abstracts:
        cols.remove("Abstract")
    w = csv.writer(buf)
    w.writerow(cols)
    i = 0
    papers = list(run.papers.values())
    papers.sort(key=lambda p: (p.seed, -p.relevance, p.title))
    for p in papers:
        if only_included and not p.included and not p.seed:
            continue
        i += 1
        row = [
            i,
            _csv_safe(p.title),
            p.doi or "",
            _csv_safe(p.authors),
            p.year or "",
            _csv_safe(p.venue),
            p.num_citations,
            p.relevance,
            p.depth,
            p.discovered_round,
            "Y" if p.seed else "N",
            "Y" if p.included else "N",
            "|".join(p.sources),
            p.url,
        ]
        if include_abstracts:
            row.append(_csv_safe(p.abstract))
        # annotation (if available)
        try:
            from .store import get_annotation
            note = get_annotation(run.run_id, p.key()) or ""
        except Exception:
            note = ""
        row.append(_csv_safe(note))
        w.writerow(row)
    return buf.getvalue()


def export_ris(run: Run, only_included: bool = True) -> str:
    buf = io.StringIO()
    papers = list(run.papers.values())
    papers.sort(key=lambda p: (p.seed, -p.relevance, p.title))
    for p in papers:
        if only_included and not p.included and not p.seed:
            continue
        buf.write("TY  - JOUR\r\n")
        buf.write(f"T1  - {p.title}\r\n")
        for a in [x.strip() for x in re.split(r"[;,]", p.authors) if x.strip()]:
            buf.write(f"AU  - {a}\r\n")
        if p.year:
            buf.write(f"PY  - {p.year}\r\n")
        if p.venue:
            buf.write(f"JO  - {p.venue}\r\n")
        if p.abstract:
            buf.write(f"AB  - {p.abstract}\r\n")
        if p.doi:
            buf.write(f"DO  - {p.doi}\r\n")
            buf.write(f"UR  - https://doi.org/{p.doi}\r\n")
        elif p.url:
            buf.write(f"UR  - {p.url}\r\n")
        buf.write("ER  - \r\n\r\n")
    return buf.getvalue()


def _bib_escape(s: str) -> str:
    return (s or "").replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def _bib_key(p: Paper, idx: int) -> str:
    surname = ""
    if p.authors:
        first = p.authors.split(";")[0].strip()
        # "Family, Given" -> "Family"
        if "," in first:
            surname = first.split(",")[0].strip()
        else:
            surname = first.split()[0]
    surname = re.sub(r"[^A-Za-z]", "", surname).lower() or "anon"
    return f"{surname}{p.year or 'xxxx'}{idx}"


def export_bibtex(run: Run, only_included: bool = True) -> str:
    buf = io.StringIO()
    papers = list(run.papers.values())
    papers.sort(key=lambda p: (p.seed, -p.relevance, p.title))
    for idx, p in enumerate(papers, 1):
        if only_included and not p.included and not p.seed:
            continue
        key = _bib_key(p, idx)
        buf.write(f"@article{{{key},\n")
        buf.write(f"  title   = {{{_bib_escape(p.title)}}},\n")
        if p.authors:
            buf.write(f"  author  = {{{_bib_escape(p.authors)}}},\n")
        if p.year:
            buf.write(f"  year    = {{{p.year}}},\n")
        if p.venue:
            buf.write(f"  journal = {{{_bib_escape(p.venue)}}},\n")
        if p.abstract:
            buf.write(f"  abstract= {{{_bib_escape(p.abstract[:500])}}},\n")
        if p.doi:
            buf.write(f"  doi     = {{{p.doi}}},\n")
        buf.write("}\n\n")
    return buf.getvalue()


def export_json(run: Run, include_abstracts: bool = True) -> str:
    d = run.to_dict(include_abstracts=include_abstracts)
    # add graph nodes/edges explicitly for machine-readable consumption
    nodes = []
    for p in run.papers.values():
        n = p.to_dict()
        n["id"] = p.key()
        nodes.append(n)
    graph = {
        "directed": True,
        "nodes": nodes,
        "edges": [
            {"source": e["source"], "target": e["target"], "direction": e["direction"]}
            for e in run.edges
        ],
    }
    d["graph"] = graph
    return json.dumps(d, indent=2, ensure_ascii=False)


def prisma_counts(run: Run) -> dict:
    """Return the 4-phase PRISMA counts."""
    total = len(run.papers)
    seeds = sum(1 for p in run.papers.values() if p.seed)
    included = sum(1 for p in run.papers.values() if p.included)
    excluded = total - included
    return {
        "identification": {
            "records_from_databases": sum(
                1 for p in run.papers.values() if "openalex" in p.sources or "crossref" in p.sources or "semantic_scholar" in p.sources
            ),
            "records_from_snowball": sum(
                1 for p in run.papers.values() if not p.seed and ("openalex" in p.sources or "semantic_scholar" in p.sources or "opencitations" in p.sources)
            ),
            "seeds": seeds,
        },
        "screening": {
            "screened": total,
            "excluded_by_relevance": sum(1 for p in run.papers.values() if not p.included and p.excluded_reason == "low_relevance"),
        },
        "eligibility": {
            "assessed": total,
            "excluded": excluded,
        },
        "included": {"included": included},
    }


def prisma_svg(run: Run, width: int = 900) -> str:
    """Render a PRISMA 2020-style 4-phase flow diagram as standalone SVG.

    Identification → Screening → Eligibility → Included, with boxes,
    arrows, and the live counts from `prisma_counts`.
    """
    pc = prisma_counts(run)
    idn = pc["identification"]
    scr = pc["screening"]
    eli = pc["eligibility"]
    inc = pc["included"]
    # layout constants
    h = 360
    box_w = 180
    box_h = 56
    gap = (width - 4 * box_w) / 5
    y_top = 60
    # theme-ish colours (read from CSS at render time would need a context;
    # use fixed but tasteful values that work on light + dark)
    fill = "#faf8f4"
    stroke = "#cfc7b8"
    accent = "#d97757"
    ink = "#2b2a27"
    muted = "#8a8782"
    green = "#6b8e7f"
    positions = []
    for i in range(4):
        x = gap + i * (box_w + gap)
        positions.append(x)

    def box(x, y, w, h, label, count, color):
        return f'''<g>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{color}" stroke-width="2"/>
  <text x="{x + w/2}" y="{y + 20}" text-anchor="middle" font-family="sans-serif" font-size="13" font-weight="700" fill="{color}">{count}</text>
  <text x="{x + w/2}" y="{y + 40}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="{ink}">{label}</text>
</g>'''

    def arrow(x1, x2, y):
        return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{muted}" stroke-width="1.5" marker-end="url(#prismaArrow)"/>'

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="{width}" height="{h}">',
        f'<defs><marker id="prismaArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{muted}"/></marker></defs>',
        f'<rect x="0" y="0" width="{width}" height="{h}" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="16" font-weight="700" fill="{ink}">PRISMA 2020 Flow Diagram</text>',
        f'<text x="{width/2}" y="46" text-anchor="middle" font-family="sans-serif" font-size="10" fill="{muted}">CuteySnowball run {run.run_id} · {len(run.papers)} records · {inc["included"]} included</text>',
    ]
    labels = ["Identification", "Screening", "Eligibility", "Included"]
    counts = [
        f'{idn["records_from_databases"] + idn["records_from_snowball"]} records',
        f'{scr["screened"]} screened',
        f'{eli["assessed"]} assessed',
        f'{inc["included"]} included',
    ]
    colors = [accent, green, accent, green]
    for i in range(4):
        x = positions[i]
        parts.append(box(x, y_top, box_w, box_h, labels[i], counts[i], colors[i]))
        if i < 3:
            x1 = positions[i] + box_w
            x2 = positions[i + 1]
            parts.append(arrow(x1, x2, y_top + box_h / 2))
    # exclusion box under screening
    exc_x = positions[1]
    exc_y = y_top + box_h + 50
    parts.append(
        f'<rect x="{exc_x}" y="{exc_y}" width="{box_w}" height="44" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1" stroke-dasharray="3 2"/>'
    )
    parts.append(
        f'<text x="{exc_x + box_w/2}" y="{exc_y + 18}" text-anchor="middle" font-family="sans-serif" font-size="12" fill="{muted}">{scr["excluded_by_relevance"]} excluded</text>'
    )
    parts.append(
        f'<text x="{exc_x + box_w/2}" y="{exc_y + 34}" text-anchor="middle" font-family="sans-serif" font-size="9" fill="{muted}">(low relevance)</text>'
    )
    parts.append(
        f'<line x1="{exc_x + box_w/2}" y1="{y_top + box_h}" x2="{exc_x + box_w/2}" y2="{exc_y}" stroke="{muted}" stroke-width="1" stroke-dasharray="3 2" marker-end="url(#prismaArrow)"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def export_subset(run: Run, keys: list, fmt: str = "ris") -> str:
    """Export only the papers whose key is in `keys`."""
    keep = set(keys or [])
    if not keep:
        return ""
    # build a filtered view
    tmp = Run(run_id=run.run_id + "-sub", mode=run.mode)
    for p in run.papers.values():
        if p.key() in keep:
            tmp.papers[p.key()] = p
    for e in run.edges:
        if e["source"] in keep and e["target"] in keep:
            tmp.edges.append(e)
    if fmt == "csv":
        return export_csv(tmp, include_abstracts=True, only_included=False)
    if fmt == "ris":
        return export_ris(tmp, only_included=False)
    if fmt == "bibtex":
        return export_bibtex(tmp, only_included=False)
    return export_json(tmp, include_abstracts=True)


def _coins_urlenc(s: str) -> str:
    """URL-encode a value for COinS (Z3988) — minimal but correct."""
    import urllib.parse
    return urllib.parse.quote(s or "", safe="")


def export_coins_html(run: Run, only_included: bool = True) -> str:
    """Render COinS spans (Z3988) for every paper.

    The Zotero browser connector detects <span class="Z3988" title="..."> on the
    page and offers a multi-item import.  Each span is invisible to the user.
    """
    import html as _html
    papers = list(run.papers.values())
    papers.sort(key=lambda p: (p.seed, -p.relevance, p.title))
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>CuteySnowball COinS export</title></head><body>"]
    parts.append("<h1>CuteySnowball corpus — COinS export</h1>")
    parts.append(f"<p>{len(papers)} papers. Open the Zotero connector in your browser to import all.</p>")
    parts.append("<ol>")
    for p in papers:
        if only_included and not p.included and not p.seed:
            continue
        # Z3988 OpenURL context object
        fields = []
        fields.append("ctx_ver=Z39.88-2004")
        fields.append("rft_val_fmt=info:ofi/fmt:kev:mtx:journal")
        if p.title:
            fields.append("rft.atitle=" + _coins_urlenc(p.title))
        if p.authors:
            # split authors and emit rft.au for each
            for a in re.split(r"[;,]", p.authors):
                a = a.strip()
                if a:
                    fields.append("rft.au=" + _coins_urlenc(a))
        if p.year:
            fields.append(f"rft.date={p.year}")
        if p.venue:
            fields.append("rft.jtitle=" + _coins_urlenc(p.venue))
        if p.doi:
            fields.append("rft_id=info:doi/" + _coins_urlenc(p.doi))
        elif p.url:
            fields.append("rft_id=" + _coins_urlenc(p.url))
        coins = "&".join(fields)
        title_esc = _html.escape(p.title or "(untitled)")
        parts.append(f'<li><span class="Z3988" title="{_html.escape(coins)}"></span>{title_esc}</li>')
    parts.append("</ol></body></html>")
    return "\n".join(parts)
