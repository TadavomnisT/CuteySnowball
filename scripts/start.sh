#!/usr/bin/env bash
# Convenience launcher for CuteySnowball.
# Usage:  ./scripts/start.sh [port]
#
# Env vars (see cutesnowball/config.py for the full list):
#   CUTESNOWBALL_PORT              (default 5000)
#   CUTESNOWBALL_MAILTO            (polite-pool address; set to your email)
#   CUTESNOWBALL_ENABLE_OPENALEX   (1/0, default 1)
#   CUTESNOWBALL_ENABLE_S2         (1/0, default 1)
#   CUTESNOWBALL_ENABLE_CROSSREF   (1/0, default 1)
#   CUTESNOWBALL_ENABLE_OPENCITATIONS (1/0, default 1)
#   CUTESNOWBALL_ENABLE_SCHOLARLY  (1/0, default 0 — Google Scholar, opt-in)
#   CUTESNOWBALL_ENABLE_SCHOLAR_SCRAPE (1/0, default 0 — Google Scholar, opt-in)
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-${CUTESNOWBALL_PORT:-5000}}"
export CUTESNOWBALL_PORT="$PORT"
echo "CuteySnowball → http://localhost:$PORT"
exec python3 run.py --port "$PORT"
