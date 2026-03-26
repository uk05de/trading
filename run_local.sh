#!/usr/bin/env bash
# Startet die App lokal aus trading_app/ — exakt derselbe Code wie in HA.
#
# Verwendung:
#   ./run_local.sh              # Streamlit App
#   ./run_local.sh bt           # Backtester (evolve_patterns)
#   ./run_local.sh bt --persistence  # Persistenz-Test
#   ./run_local.sh bt --breakeven    # Breakeven-Test
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/trading_app"

export TRADING_DB_PATH="${TRADING_DB_PATH:-$ROOT/trading.db}"

if [ "$1" = "bt" ]; then
    shift
    exec "$ROOT/.venv/bin/python3" bt_run.py "$@"
else
    exec "$ROOT/.venv/bin/streamlit" run app.py \
        --server.port="${PORT:-8501}" \
        --server.address=0.0.0.0 \
        --browser.gatherUsageStats=false \
        --server.headless=true
fi
