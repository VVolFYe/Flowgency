#!/usr/bin/env bash
set -euo pipefail

SUMO_ROOT="${SUMO_HOME:-/usr/share/sumo}"
SCENARIO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCENARIO_DIR"

python3 "$SUMO_ROOT/tools/randomTrips.py" \
  --net-file london.net.xml \
  --output-trip-file london.trips.xml \
  --route-file london.rou.xml \
  --vehicle-class passenger \
  --seed 42 \
  --begin 0 \
  --end 900 \
  --period 12 \
  --min-distance 500 \
  --fringe-factor max \
  --trip-attributes 'departLane="best" departSpeed="max"' \
  --validate \
  --remove-loops \
  --error-log route_errors.log \
  --verbose
