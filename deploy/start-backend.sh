#!/usr/bin/env bash
set -euo pipefail
release="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$release"
set -a
source "$HOME/flowgency/shared/backend.env"
set +a
source "$release/.venv/bin/activate"
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"
export FLOWGENCY_ANALYTICS_DB="${FLOWGENCY_ANALYTICS_DB:-$HOME/flowgency/shared/analytics.sqlite3}"
# One worker owns the shared in-memory simulation for every viewer.
exec python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000 --workers 1
