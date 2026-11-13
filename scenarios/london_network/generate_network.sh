#!/usr/bin/env bash
set -euo pipefail

SUMO_ROOT="${SUMO_HOME:-/usr/share/sumo}"
SCENARIO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCENARIO_DIR"

python3 "$SUMO_ROOT/tools/osmBuild.py" \
  --osm-file london_bbox.osm.xml \
  --prefix london \
  --output-directory . \
  --vehicle-classes passenger \
  --netconvert-options=--geometry.remove,--roundabouts.guess,--ramps.guess,--junctions.join,--junctions.join-output,london.joined.xml,--tls.guess-signals,--tls.discard-simple,--lefthand,--no-turnarounds,--keep-edges.components,1,--output.original-names,--output.street-names \
  --verbose
