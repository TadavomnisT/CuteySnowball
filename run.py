#!/usr/bin/env python3
"""CuteySnowball entry point.

    python3 run.py            # serve on 0.0.0.0:5000
    CUTESNOWBALL_PORT=8080 python3 run.py

CuteySnowball is a pure-Python Forward/Backward Snowballing tool for
Systematic Literature Reviews (SLR) and Systematic Mapping Studies (SMS).

It is licensed under the GNU GPL v3.0.  See LICENSE for details.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Make sure the package is importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cutesnowball import create_app  # noqa: E402
from cutesnowball.config import config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="CuteySnowball — snowballing for SLRs")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    parser.add_argument("--debug", action="store_true", default=config.debug)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # init DB
    from cutesnowball import store as store_mod

    store_mod.init_db()

    app = create_app()
    print(
        "\n  CuteySnowball starting...\n"
        "  ────────────────────────────────────────────\n"
        f"  Open  http://localhost:{args.port}\n"
        "  Sources enabled:\n"
        f"    openalex          : {config.enable_openalex}\n"
        f"    semantic_scholar  : {config.enable_semantic_scholar}\n"
        f"    crossref          : {config.enable_crossref}\n"
        f"    opencitations     : {config.enable_opencitations}\n"
        f"    scholarly (GS)    : {config.enable_scholarly}\n"
        f"    scholar_scrape    : {config.enable_scholar_scrape}\n"
        "  ────────────────────────────────────────────\n"
        "  GPL-3.0 — no warranty.  See LICENSE.\n",
        flush=True,
    )
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
