#!/usr/bin/env bash
set -euo pipefail

SUMO_ROOT="${SUMO_HOME:-/usr/share/sumo}"
SCENARIO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCENARIO_DIR"

python3 "$SUMO_ROOT/tools/osmGet.py" \
  --bbox=-0.1225,51.4720,-0.0980,51.4870 \
  --prefix london \
  --output-dir . \
  --road-types '{"highway":["."]}' \
  --query-output import.overpass.xml \
  --retries 3 \
  --retry-delay 2 \
  --verbose
