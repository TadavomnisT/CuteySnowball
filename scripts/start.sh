#!/usr/bin/env bash
# Convenience launcher for CuteySnowball.
# Usage:  ./scripts/start.sh [port]
#
# If a virtualenv exists at .venv/, it is activated automatically.
# Otherwise the system python3 is used.
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

# Activate venv if it exists, otherwise use system python3
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi

# Find python3 — check VIRTUAL_ENV first, then PATH
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python3" ]; then
  PYTHON="${VIRTUAL_ENV}/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "ERROR: python3 not found. Install Python 3.8+ or create a venv: python3 -m venv .venv"
  exit 1
fi

PORT="${1:-${CUTESNOWBALL_PORT:-5000}}"
export CUTESNOWBALL_PORT="$PORT"
echo "CuteySnowball → http://localhost:$PORT"
exec "$PYTHON" run.py --port "$PORT"
