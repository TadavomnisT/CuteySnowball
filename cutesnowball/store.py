"""SQLite persistence for snowball runs.

Lets the UI reload a finished/running run after a page refresh, and lets
us resume a long run that was interrupted.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional

from .config import config
from .models import Run, Paper, new_run_id


_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    conn = sqlite3.connect(config.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    message TEXT,
                    created_at REAL,
                    started_at REAL,
                    finished_at REAL,
                    data TEXT,
                    error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at)")
            # DOI -> Paper metadata cache (cross-run).  Keyed on normalised DOI.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_cache (
                    doi TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_cache_at ON paper_cache(cached_at)"
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# DOI -> Paper cross-run cache
# ---------------------------------------------------------------------------

def cache_get_paper(doi: str):
    """Return a cached Paper for this DOI, or None."""
    if not doi:
        return None
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT data FROM paper_cache WHERE doi=?", (doi.lower(),)
            ).fetchone()
            if not row:
                return None
            try:
                return Paper.from_dict(json.loads(row["data"]))
            except Exception:
                return None
        finally:
            conn.close()


def cache_put_paper(paper) -> None:
    """Cache a paper (must have a DOI).  No-op if no DOI."""
    if not paper or not paper.doi:
        return
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO paper_cache (doi, data, cached_at) VALUES (?, ?, ?)",
                (paper.doi.lower(), json.dumps(paper.to_dict()), time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def cache_stats() -> dict:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n, MIN(cached_at) AS oldest, MAX(cached_at) AS newest FROM paper_cache"
            ).fetchone()
            return {"entries": row["n"] if row else 0, "oldest": row["oldest"] if row else None, "newest": row["newest"] if row else None}
        finally:
            conn.close()


def save_run(run: Run) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO runs (run_id, mode, status, phase, message, created_at,
                                  started_at, finished_at, data, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    phase=excluded.phase,
                    message=excluded.message,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    data=excluded.data,
                    error=excluded.error
                """,
                (
                    run.run_id,
                    run.mode,
                    run.status,
                    run.phase,
                    run.message,
                    run.created_at,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.to_dict()),
                    run.error,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def load_run(run_id: str) -> Optional[Run]:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute("SELECT data FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            d = json.loads(row["data"])
            return _dict_to_run(d)
        finally:
            conn.close()


def list_runs(limit: int = 20) -> List[Dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT run_id, mode, status, phase, message, created_at, finished_at, data FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            out = []
            for r in rows:
                item = {k: r[k] for k in ("run_id", "mode", "status", "phase", "message", "created_at", "finished_at")}
                # extract tags from the JSON data column
                try:
                    d = json.loads(r["data"]) if r["data"] else {}
                    item["tags"] = d.get("tags", [])
                    item["paper_count"] = d.get("paper_count", 0)
                except Exception:
                    item["tags"] = []
                    item["paper_count"] = 0
                out.append(item)
            return out
        finally:
            conn.close()


def _dict_to_run(d: dict) -> Run:
    r = Run(run_id=d["run_id"], mode=d["mode"])
    r.status = d.get("status", "done")
    r.phase = d.get("phase", "included")
    r.message = d.get("message", "")
    r.tags = d.get("tags", [])
    r.created_at = d.get("created_at", 0.0)
    r.started_at = d.get("started_at")
    r.finished_at = d.get("finished_at")
    r.error = d.get("error", "")
    r.seeds_input = d.get("seeds_input", [])
    r.keywords = d.get("keywords", [])
    r.options = d.get("options", {})
    r.stats = d.get("stats", {})
    r.edges = d.get("edges", [])
    for pd in d.get("papers", []):
        p = Paper.from_dict(pd)
        p.seed = pd.get("seed", False)
        p.depth = pd.get("depth", 0)
        p.discovered_round = pd.get("discovered_round", 0)
        p.relevance = pd.get("relevance", 0.0)
        p.included = pd.get("included", True)
        p.excluded_reason = pd.get("excluded_reason", "")
        r.papers[p.key()] = p
    return r


def new_run(mode: str, seeds_input: List[str], keywords: List[str], options: Dict) -> Run:
    r = Run(run_id=new_run_id(), mode=mode, seeds_input=seeds_input, keywords=keywords, options=options)
    save_run(r)
    return r
