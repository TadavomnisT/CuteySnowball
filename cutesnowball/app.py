"""Flask application factory + routes.

Routes:
  GET  /                       -> the SPA (static HTML)
  GET  /api/config             -> default config + enabled sources
  GET  /api/sources            -> per-adapter health
  POST /api/search             -> quick keyword search (for option 2 seed picking)
  POST /api/run                -> start a snowball run (returns run_id)
  GET  /api/run/<id>           -> current run state (papers, graph, stats)
  GET  /api/run/<id>/events    -> SSE stream of live progress
  POST /api/run/<id>/stop      -> stop a running run
  GET  /api/run/<id>/export    -> ?format=ris|csv|json|bibtex
  GET  /api/runs               -> list recent runs
  GET  /api/health             -> liveness probe

PDF upload:
  POST /api/run                -> multipart: 'pdfs' files + 'mode=paper' + 'dois' + 'keywords'
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Dict, List

from flask import Flask, Response, request, jsonify, send_from_directory, stream_with_context

from .config import config
from .engines import build_adapters
from .models import Paper, Run
from . import store as store_mod
from . import snowball as snowball_mod
from . import export as export_mod

log = logging.getLogger("cutesnowball.app")
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Run event bus: per-run queue that the SSE route drains.
# ---------------------------------------------------------------------------
_EVENTS: Dict[str, "queue.Queue"] = {}
_EVENTS_LOCK = threading.Lock()


def _get_queue(run_id: str) -> "queue.Queue":
    with _EVENTS_LOCK:
        q = _EVENTS.get(run_id)
        if q is None:
            q = queue.Queue()
            _EVENTS[run_id] = q
        return q


def _drop_queue(run_id: str):
    with _EVENTS_LOCK:
        _EVENTS.pop(run_id, None)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(static_folder: str = None) -> Flask:
    if static_folder is None:
        here = os.path.dirname(os.path.abspath(__file__))
        static_folder = os.path.normpath(os.path.join(here, "..", "static"))

    store_mod.init_db()

    app = Flask(
        __name__,
        static_folder=static_folder,
        static_url_path="/static",
    )
    app.config["SECRET_KEY"] = config.secret_key

    # --- static SPA ---------------------------------------------------------
    @app.route("/")
    def index():
        return send_from_directory(static_folder, "index.html")

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(static_folder, "img", "favicon.svg")

    # --- config + health ----------------------------------------------------
    @app.route("/api/config")
    def get_config():
        return jsonify(
            {
                "version": "0.1.0",
                "mailto": config.mailto,
                "sources": {
                    "openalex": config.enable_openalex,
                    "semantic_scholar": config.enable_semantic_scholar,
                    "crossref": config.enable_crossref,
                    "opencitations": config.enable_opencitations,
                    "scholarly": config.enable_scholarly,
                    "scholar_scrape": config.enable_scholar_scrape,
                },
                "limits": {
                    "max_iterations": config.max_iterations,
                    "max_total_papers": config.max_total_papers,
                    "min_relevance": config.min_relevance,
                    "per_round_cap": config.per_round_cap,
                    "max_forward_pages_openalex": config.max_forward_pages_openalex,
                    "max_s2_pages": config.max_s2_pages,
                    "page_delay_ms": config.page_delay_ms,
                    "min_delay_per_host": config.min_delay_per_host,
                    "jitter": config.jitter,
                },
                "weights": config.source_weights(),
            }
        )

    @app.route("/api/sources")
    def sources():
        out = []
        for ad in build_adapters(config):
            healthy = True
            try:
                healthy = ad.healthy()
            except Exception:
                healthy = False
            out.append({"name": ad.name, "healthy": healthy})
        return jsonify(out)

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "version": "0.8.0"})

    # --- quick search (option 2 seed picking) -------------------------------
    @app.route("/api/search", methods=["POST"])
    def search():
        body = request.get_json(force=True, silent=True) or {}
        query = (body.get("query") or "").strip()
        limit = int(body.get("limit", 10))
        if not query:
            return jsonify({"error": "query required"}), 400
        out: List[dict] = []
        seen = set()
        for ad in build_adapters(config):
            try:
                for p in ad.search(query, limit=limit) or []:
                    k = p.key()
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append(p.to_dict())
                    if len(out) >= limit * 2:
                        break
            except Exception as exc:
                log.warning("search via %s failed: %s", ad.name, exc)
            if len(out) >= limit * 2:
                break
        return jsonify({"query": query, "results": out[:limit * 2]})

    # --- duplicate detection (check before starting a run) ------------------
    @app.route("/api/check-duplicate", methods=["POST"])
    def check_duplicate():
        body = request.get_json(force=True, silent=True) or {}
        seeds = body.get("seeds") or []
        keywords = body.get("keywords") or []
        if not seeds and not keywords:
            return jsonify({"duplicate": False})
        # normalise seeds the same way the snowballer does
        norm = []
        for s in seeds:
            s = (s or "").strip().lower()
            if "doi.org/" in s:
                s = s.split("doi.org/", 1)[1]
            s = s.rstrip(".,;)]}")
            if s:
                norm.append(s)
        runs = store_mod.list_runs(limit=50)
        dupes = []
        for r in runs:
            full = store_mod.load_run(r["run_id"])
            if not full:
                continue
            run_seeds_norm = []
            for s in full.seeds_input:
                s = (s or "").strip().lower()
                if "doi.org/" in s:
                    s = s.split("doi.org/", 1)[1]
                s = s.rstrip(".,;)]}")
                if s:
                    run_seeds_norm.append(s)
            # check seed overlap
            overlap = set(norm) & set(run_seeds_norm)
            if overlap:
                dupes.append({
                    "run_id": r["run_id"],
                    "mode": r["mode"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "tags": r.get("tags", []),
                    "overlap": sorted(overlap)[:5],
                    "paper_count": r.get("paper_count", 0),
                })
            # check keyword overlap
            if keywords:
                full_kw = " ".join(full.keywords or []).lower()
                for kw in keywords:
                    if kw.lower() in full_kw:
                        dupes.append({
                            "run_id": r["run_id"],
                            "mode": r["mode"],
                            "status": r["status"],
                            "created_at": r["created_at"],
                            "tags": r.get("tags", []),
                            "keyword_match": kw,
                            "paper_count": r.get("paper_count", 0),
                        })
        return jsonify({"duplicate": len(dupes) > 0, "matches": dupes[:5]})

    # --- start a run --------------------------------------------------------
    @app.route("/api/run", methods=["POST"])
    def start_run_route():
        mode = (request.form.get("mode") or request.json.get("mode") if request.is_json else request.form.get("mode")) or "paper"
        # accept JSON too
        if request.is_json:
            body = request.get_json(force=True, silent=True) or {}
            mode = body.get("mode", "paper")
            seeds_input = [s for s in body.get("seeds", []) if s]
            keywords = [k for k in body.get("keywords", []) if k]
            options = body.get("options", {})
        else:
            seeds_input = []
            dois = request.form.get("dois", "")
            for line in dois.splitlines():
                line = line.strip()
                if line:
                    seeds_input.append(line)
            keywords = []
            kw = request.form.get("keywords", "")
            for k in kw.replace(",", "\n").splitlines():
                k = k.strip()
                if k:
                    keywords.append(k)
            options = json.loads(request.form.get("options") or "{}")
            # handle uploaded PDFs
            files = request.files.getlist("pdfs")
            for i, f in enumerate(files):
                data = f.read()
                if data:
                    # store the PDF on disk so the worker can read it
                    upload_dir = os.path.join(os.path.dirname(config.db_path), "uploads", str(int(time.time() * 1000)))
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, f"seed_{i}.pdf")
                    with open(path, "wb") as fh:
                        fh.write(data)
                    seeds_input.append("pdf:" + path)
        if not seeds_input and not keywords:
            return jsonify({"error": "no seeds or keywords"}), 400
        run = store_mod.new_run(
            mode=mode, seeds_input=seeds_input, keywords=keywords, options=options
        )
        q = _get_queue(run.run_id)
        # worker thread
        def worker():
            def cb(ev):
                q.put(ev)
            try:
                snowball_mod.start_run(run.run_id, mode, seeds_input, keywords, options, event_cb=cb)
            finally:
                q.put({"_done": True})

        t = threading.Thread(target=worker, daemon=True, name=f"snowball-{run.run_id}")
        t.start()
        return jsonify({"run_id": run.run_id, "status": "started"})

    # --- run state ----------------------------------------------------------
    @app.route("/api/run/<run_id>")
    def get_run(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        return jsonify(run.to_dict(include_abstracts=True))

    @app.route("/api/run/<run_id>/stats")
    def get_stats(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        return jsonify(run.stats_snapshot())

    # --- SSE live progress --------------------------------------------------
    @app.route("/api/run/<run_id>/events")
    def events(run_id):
        def gen():
            q = _get_queue(run_id)
            # if the run is already done, send the final snapshot and close
            run = store_mod.load_run(run_id)
            if run and run.status in ("done", "error"):
                yield f"event: snapshot\ndata: {json.dumps(run.to_dict())}\n\n"
                yield "event: done\ndata: {}\n\n"
                _drop_queue(run_id)
                return
            # keep alive pings
            last_ping = time.time()
            while True:
                try:
                    ev = q.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_ping > 15:
                        yield ": ping\n\n"
                        last_ping = time.time()
                    # check if run finished
                    run = store_mod.load_run(run_id)
                    if run and run.status in ("done", "error"):
                        yield f"event: snapshot\ndata: {json.dumps(run.to_dict())}\n\n"
                        yield "event: done\ndata: {}\n\n"
                        _drop_queue(run_id)
                        return
                    continue
                if isinstance(ev, dict) and ev.get("_done"):
                    run = store_mod.load_run(run_id)
                    if run:
                        yield f"event: snapshot\ndata: {json.dumps(run.to_dict())}\n\n"
                    yield "event: done\ndata: {}\n\n"
                    _drop_queue(run_id)
                    return
                yield f"event: progress\ndata: {json.dumps(ev)}\n\n"

        return Response(
            stream_with_context(gen()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # --- stop a run ---------------------------------------------------------
    @app.route("/api/run/<run_id>/stop", methods=["POST"])
    def stop_run(run_id):
        ok = snowball_mod.stop_run(run_id)
        return jsonify({"stopped": ok})

    # --- resume a stopped/errored run ---------------------------------------
    @app.route("/api/run/<run_id>/resume", methods=["POST"])
    def resume_run_route(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        if run.status == "running":
            return jsonify({"error": "already running"}), 409
        q = _get_queue(run_id)
        # clear stale events
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break

        def worker():
            def cb(ev):
                q.put(ev)
            try:
                snowball_mod.resume_run(run_id, event_cb=cb)
            finally:
                q.put({"_done": True})

        t = threading.Thread(target=worker, daemon=True, name=f"resume-{run_id}")
        t.start()
        return jsonify({"run_id": run_id, "status": "resumed"})

    # --- export -------------------------------------------------------------
    @app.route("/api/run/<run_id>/export")
    def export(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        fmt = request.args.get("format", "json")
        only_included = request.args.get("all") != "1"
        include_abs = request.args.get("abstracts") != "0"
        if fmt == "csv":
            return Response(
                export_mod.export_csv(run, include_abstracts=include_abs, only_included=only_included),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=cuteysnowball_{run_id}.csv"},
            )
        if fmt == "ris":
            return Response(
                export_mod.export_ris(run, only_included=only_included),
                mimetype="application/x-research-info-systems",
                headers={"Content-Disposition": f"attachment; filename=cuteysnowball_{run_id}.ris"},
            )
        if fmt == "bibtex":
            return Response(
                export_mod.export_bibtex(run, only_included=only_included),
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename=cuteysnowball_{run_id}.bib"},
            )
        # default: json
        return Response(
            export_mod.export_json(run, include_abstracts=include_abs),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=cuteysnowball_{run_id}.json"},
        )

    # --- COinS (Z3988) HTML page for Zotero multi-import -------------------
    @app.route("/api/run/<run_id>/coins")
    def coins(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        only_included = request.args.get("all") != "1"
        return Response(
            export_mod.export_coins_html(run, only_included=only_included),
            mimetype="text/html",
        )

    # --- prisma counts ------------------------------------------------------
    @app.route("/api/run/<run_id>/prisma")
    def prisma(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        fmt = request.args.get("format", "json")
        if fmt == "svg":
            svg = export_mod.prisma_svg(run)
            return Response(svg, mimetype="image/svg+xml",
                             headers={"Content-Disposition": f"attachment; filename=prisma_{run_id}.svg"})
        return jsonify(export_mod.prisma_counts(run))

    # --- bulk export (selected papers) -------------------------------------
    @app.route("/api/run/<run_id>/export-selected", methods=["POST"])
    def export_selected(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        body = request.get_json(force=True, silent=True) or {}
        keys = body.get("keys") or []
        fmt = body.get("format", "ris")
        if not keys:
            return jsonify({"error": "no keys provided"}), 400
        data = export_mod.export_subset(run, keys, fmt=fmt)
        mt = {
            "csv": "text/csv", "ris": "application/x-research-info-systems",
            "bibtex": "text/plain", "json": "application/json",
        }.get(fmt, "text/plain")
        ext = "bib" if fmt == "bibtex" else fmt
        return Response(
            data, mimetype=mt,
            headers={"Content-Disposition": f"attachment; filename=cuteysnowball_{run_id}_selected.{ext}"},
        )

    # --- settings (runtime overrides + current config) ---------------------
    _SETTINGS_OVERRIDES = {"mailto": None, "min_relevance": None, "max_iterations": None, "per_round_cap": None}

    @app.route("/api/settings", methods=["GET", "POST"])
    def settings():
        if request.method == "POST":
            body = request.get_json(force=True, silent=True) or {}
            for k in list(_SETTINGS_OVERRIDES.keys()):
                if k in body and body[k] is not None:
                    _SETTINGS_OVERRIDES[k] = body[k]
                    # apply to the live config where possible
                    if k == "mailto":
                        config.mailto = str(body[k])
                    elif k == "min_relevance":
                        config.min_relevance = float(body[k])
                    elif k == "max_iterations":
                        config.max_iterations = int(body[k])
                    elif k == "per_round_cap":
                        config.per_round_cap = int(body[k])
            return jsonify({"ok": True, "overrides": _SETTINGS_OVERRIDES})
        # GET
        return jsonify({
            "mailto": config.mailto,
            "min_relevance": config.min_relevance,
            "max_iterations": config.max_iterations,
            "per_round_cap": config.per_round_cap,
            "max_total_papers": config.max_total_papers,
            "min_delay_per_host": config.min_delay_per_host,
            "sources": {
                "openalex": config.enable_openalex,
                "semantic_scholar": config.enable_semantic_scholar,
                "crossref": config.enable_crossref,
                "opencitations": config.enable_opencitations,
                "scholarly": config.enable_scholarly,
                "scholar_scrape": config.enable_scholar_scrape,
            },
            "weights": config.source_weights(),
            "cache": store_mod.cache_stats(),
        })

    @app.route("/api/cache/clear", methods=["POST"])
    def clear_cache():
        with store_mod._lock:
            conn = store_mod._connect()
            try:
                conn.execute("DELETE FROM paper_cache")
                conn.commit()
            finally:
                conn.close()
        return jsonify({"ok": True, "stats": store_mod.cache_stats()})

    # --- single-paper export (for the detail panel) -------------------------
    @app.route("/api/run/<run_id>/paper/<path:paper_key>")
    def paper_detail(run_id, paper_key):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        # paper_key is like "doi:10.xxx/yyy" or "t:abcd1234" — unquote it
        from urllib.parse import unquote
        pk = unquote(paper_key).strip()
        p = run.papers.get(pk)
        if not p:
            # try matching by doi suffix
            for pp in run.papers.values():
                if pp.doi and ("doi:" + pp.doi) == pk:
                    p = pp
                    break
            if not p:
                return jsonify({"error": "paper not found", "key": pk}), 404
        fmt = request.args.get("format", "json")
        if fmt == "bibtex":
            # build a 1-entry bibtex
            import re as _re
            from .models import Paper as _P
            tmp = Run(run_id="single", mode="paper")
            tmp.papers[p.key()] = p
            return Response(
                export_mod.export_bibtex(tmp, only_included=False),
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename={pk.replace(':', '_').replace('/', '_')}.bib"},
            )
        if fmt == "ris":
            tmp = Run(run_id="single", mode="paper")
            tmp.papers[p.key()] = p
            return Response(
                export_mod.export_ris(tmp, only_included=False),
                mimetype="application/x-research-info-systems",
                headers={"Content-Disposition": f"attachment; filename={pk.replace(':', '_').replace('/', '_')}.ris"},
            )
        # default: json with neighbours
        d = p.to_dict()
        # build incoming + outgoing edge lists
        incoming, outgoing = [], []
        for e in run.edges:
            if e["target"] == pk:
                src = run.papers.get(e["source"])
                if src:
                    incoming.append({"paper": src.to_dict(), "direction": e["direction"]})
            if e["source"] == pk:
                tgt = run.papers.get(e["target"])
                if tgt:
                    outgoing.append({"paper": tgt.to_dict(), "direction": e["direction"]})
        d["incoming"] = incoming
        d["outgoing"] = outgoing
        return jsonify(d)

    # --- list runs ----------------------------------------------------------
    @app.route("/api/runs")
    def list_runs():
        return jsonify(store_mod.list_runs())

    # --- relevance-score explainer -----------------------------------------
    @app.route("/api/run/<run_id>/explain/<path:paper_key>")
    def explain(run_id, paper_key):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        from urllib.parse import unquote
        from .relevance import RelevanceScorer
        pk = unquote(paper_key).strip()
        p = run.papers.get(pk)
        if not p:
            for pp in run.papers.values():
                if pp.doi and ("doi:" + pp.doi) == pk:
                    p = pp
                    break
            if not p:
                return jsonify({"error": "paper not found"}), 404
        seeds = [sp for sp in run.papers.values() if sp.seed]
        if not seeds:
            return jsonify({"error": "no seeds in run"}), 400
        weights = None
        if isinstance(run.options, dict) and run.options.get("weights"):
            weights = run.options["weights"]
        scorer = RelevanceScorer(seeds, w=weights)
        return jsonify(scorer.explain(p))

    # --- run comparison -----------------------------------------------------
    @app.route("/api/compare")
    def compare_runs():
        a_id = request.args.get("a")
        b_id = request.args.get("b")
        if not a_id or not b_id:
            return jsonify({"error": "need ?a=<id>&b=<id>"}), 400
        run_a = store_mod.load_run(a_id)
        run_b = store_mod.load_run(b_id)
        if not run_a or not run_b:
            return jsonify({"error": "run not found"}), 404
        keys_a = set(run_a.papers.keys())
        keys_b = set(run_b.papers.keys())
        only_a = sorted(
            [run_a.papers[k].to_dict() for k in (keys_a - keys_b)],
            key=lambda p: -p.get("relevance", 0),
        )
        only_b = sorted(
            [run_b.papers[k].to_dict() for k in (keys_b - keys_a)],
            key=lambda p: -p.get("relevance", 0),
        )
        common_keys = keys_a & keys_b
        shifted = []
        for k in common_keys:
            pa = run_a.papers[k]
            pb = run_b.papers[k]
            ra = pa.relevance or 0
            rb = pb.relevance or 0
            if abs(ra - rb) > 0.01:
                shifted.append({
                    "key": k,
                    "title": pa.title or pb.title or "(untitled)",
                    "year": pa.year or pb.year,
                    "doi": pa.doi or pb.doi,
                    "rel_a": round(ra, 3),
                    "rel_b": round(rb, 3),
                    "delta": round(rb - ra, 3),
                })
        shifted.sort(key=lambda x: -abs(x["delta"]))
        result = {
            "a": {"run_id": a_id, "paper_count": len(keys_a), "mode": run_a.mode, "created_at": run_a.created_at},
            "b": {"run_id": b_id, "paper_count": len(keys_b), "mode": run_b.mode, "created_at": run_b.created_at},
            "common": len(common_keys),
            "only_a_count": len(only_a),
            "only_b_count": len(only_b),
            "shifted_count": len(shifted),
            "only_a": only_a[:50],
            "only_b": only_b[:50],
            "shifted": shifted[:50],
        }
        fmt = request.args.get("format")
        if fmt == "csv":
            import csv as _csv
            import io as _io
            buf = _io.StringIO()
            buf.write("\ufeff")
            w = _csv.writer(buf)
            w.writerow(["Section", "Title", "Year", "DOI", "Rel_A", "Rel_B", "Delta"])
            for p in result["only_a"]:
                w.writerow(["only_a", p.get("title", ""), p.get("year", ""), p.get("doi", ""), p.get("relevance", 0), "", ""])
            for p in result["only_b"]:
                w.writerow(["only_b", p.get("title", ""), p.get("year", ""), p.get("doi", ""), "", p.get("relevance", 0), ""])
            for s in result["shifted"]:
                w.writerow(["shifted", s["title"], s.get("year", ""), s.get("doi", ""), s["rel_a"], s["rel_b"], s["delta"]])
            return Response(buf.getvalue(), mimetype="text/csv",
                             headers={"Content-Disposition": f"attachment; filename=compare_{a_id[:8]}_{b_id[:8]}.csv"})
        if fmt == "json":
            return Response(json.dumps(result, indent=2, ensure_ascii=False), mimetype="application/json",
                            headers={"Content-Disposition": f"attachment; filename=compare_{a_id[:8]}_{b_id[:8]}.json"})
        return jsonify(result)

    # --- LLM abstract summarisation (opt-in, via z-ai CLI) ------------------
    @app.route("/api/run/<run_id>/summarise/<path:paper_key>", methods=["POST"])
    def summarise(run_id, paper_key):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        from urllib.parse import unquote
        pk = unquote(paper_key).strip()
        p = run.papers.get(pk)
        if not p:
            for pp in run.papers.values():
                if pp.doi and ("doi:" + pp.doi) == pk:
                    p = pp
                    break
            if not p:
                return jsonify({"error": "paper not found"}), 404
        text = (p.title or "") + ". " + (p.abstract or "")
        if len(text) < 40:
            return jsonify({"error": "paper has no abstract to summarise"}), 400
        try:
            import subprocess
            prompt = (
                "Summarise this academic paper in ONE plain sentence (max ~40 words). "
                "Be specific about the contribution. No preamble.\n\n"
                f"Title: {p.title or '(untitled)'}\n"
                f"Abstract: {p.abstract or '(no abstract)'}"
            )
            r = subprocess.run(
                ["z-ai", "chat", "-p", prompt],
                capture_output=True, text=True, timeout=45,
            )
            if r.returncode != 0:
                return jsonify({"error": "z-ai CLI failed", "stderr": r.stderr[:500]}), 502
            # parse JSON output (strip status lines)
            lines = [l for l in r.stdout.split("\n") if not l.startswith("🚀")]
            data = json.loads("\n".join(lines))
            summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not summary:
                return jsonify({"error": "empty summary"}), 502
            return jsonify({"summary": summary, "paper_key": pk})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "summarisation timed out"}), 504
        except FileNotFoundError:
            return jsonify({"error": "z-ai CLI not installed on server"}), 501
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # --- run tags (add/remove) ----------------------------------------------
    @app.route("/api/run/<run_id>/tags", methods=["POST"])
    def set_tags(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        body = request.get_json(force=True, silent=True) or {}
        tags = body.get("tags") or []
        if not isinstance(tags, list):
            return jsonify({"error": "tags must be a list"}), 400
        # sanitize: strip + lowercase + unique + cap 10
        clean = list(dict.fromkeys(str(t).strip().lower() for t in tags if str(t).strip()))[:10]
        run.tags = clean
        store_mod.save_run(run)
        return jsonify({"ok": True, "tags": run.tags})

    # --- batch LLM summarisation (streaming via SSE) ------------------------
    @app.route("/api/run/<run_id>/summarise-batch", methods=["GET"])
    def summarise_batch(run_id):
        run = store_mod.load_run(run_id)
        if not run:
            return jsonify({"error": "not found"}), 404
        import subprocess as _sp

        def gen():
            # pick included papers with abstracts, sorted by relevance
            papers = sorted(
                [p for p in run.papers.values() if p.included and (p.abstract or "") and len(p.abstract) > 40],
                key=lambda p: -p.relevance,
            )
            limit = min(int(request.args.get("limit", 20)), len(papers))
            papers = papers[:limit]
            yield f"event: start\ndata: {json.dumps({'count': len(papers)})}\n\n"
            done = 0
            for p in papers:
                try:
                    prompt = (
                        "Summarise this academic paper in ONE plain sentence (max ~40 words). "
                        "Be specific about the contribution. No preamble.\n\n"
                        f"Title: {p.title or '(untitled)'}\n"
                        f"Abstract: {p.abstract or '(no abstract)'}"
                    )
                    r = _sp.run(["z-ai", "chat", "-p", prompt], capture_output=True, text=True, timeout=45)
                    if r.returncode != 0:
                        yield f"event: error\ndata: {json.dumps({'key': p.key(), 'error': 'cli failed'})}\n\n"
                        continue
                    lines = [l for l in r.stdout.split("\n") if not l.startswith("🚀")]
                    data = json.loads("\n".join(lines))
                    summary = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    done += 1
                    yield f"event: summary\ndata: {json.dumps({'key': p.key(), 'title': p.title, 'summary': summary, 'done': done, 'total': len(papers)})}\n\n"
                except _sp.TimeoutExpired:
                    yield f"event: error\ndata: {json.dumps({'key': p.key(), 'error': 'timeout'})}\n\n"
                except Exception as exc:
                    yield f"event: error\ndata: {json.dumps({'key': p.key(), 'error': str(exc)})}\n\n"
            yield f"event: done\ndata: {json.dumps({'done': done, 'total': len(papers)})}\n\n"

        return Response(stream_with_context(gen()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    return app
