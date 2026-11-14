# Flowgency backend

The Phase 1.3 backend runs one local SUMO process behind a dedicated simulation worker and exposes lifecycle controls through FastAPI. API and WebSocket code never calls TraCI directly.

## Dependencies

The current machine already provides compatible FastAPI, Uvicorn, Pydantic, Starlette, and HTTPX versions under Python 3.14.7. No installation was required. For a clean developer environment, create a virtual environment in a Linux-native developer directory outside this NTFS repository, then install the repository manifest:

```bash
python3 -m venv /path/on/linux/flowgency-venv
/path/on/linux/flowgency-venv/bin/pip install -r backend/requirements.txt
```

SUMO 1.27.1 and its bundled Python tools must be installed separately. Set `SUMO_HOME` when they are not under a standard Linux path.

## Run locally

From the repository root:

```bash
python3 -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Useful requests:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/simulation/status
curl http://127.0.0.1:8000/api/simulation/scenarios
curl http://127.0.0.1:8000/api/simulation/network
curl 'http://127.0.0.1:8000/api/simulation/network?scenario_id=london_normal'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"london_unbalanced","simulation_speed":4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"london_unbalanced","control_mode":"adaptive","simulation_speed":4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/pause
curl -X POST http://127.0.0.1:8000/api/simulation/speed \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 8.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/resume \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/reset
curl -X POST http://127.0.0.1:8000/api/simulation/stop
```

Connect a WebSocket client to `ws://127.0.0.1:8000/ws/simulation`. Messages are envelopes with `type` equal to `status` or `snapshot` and a corresponding `data` object. The endpoint sends at most four messages per wall-clock second per client.

`GET /api/simulation/network` is static, read-only, cached per scenario network, and never accesses TraCI. It accepts an explicit `scenario_id`; otherwise it follows the active scenario and defaults to synthetic while idle. London geometry preserves UTM zone 30 projection metadata, external/internal lanes, junctions, TLS positions, and controlled links.

Geometry and vehicle positions use unchanged SUMO Cartesian metres with positive Y pointing upward. Browser canvas and many screen coordinate systems use positive Y downward. A frontend should use one shared transform for geometry and vehicles, for example `screen_y = viewport_height - (sumo_y - min_y) * scale`, and should not mutate API coordinates into latitude/longitude.

Development CORS is restricted to `http://localhost:3000` and `http://127.0.0.1:3000`; no wildcard origin is enabled.

`simulation_speed` means simulated seconds advanced per wall-clock second and accepts values from `0.1` through `100`. Reset starts a fresh SUMO process at time zero and leaves it paused. Stop releases SUMO and returns to `idle`.

`POST /api/simulation/start` accepts `"control_mode": "fixed"`, `"adaptive"`, or `"adaptive_with_emergency_priority"`. Omitting it selects the scenario default (`fixed`, except for `single_intersection_emergency`). The verified synthetic adaptive policy samples halting queues each simulated second, protects a 10-second minimum green, and normally limits green to 45 seconds. Emergency priority recognizes declared SUMO types `ambulance`, `fire_brigade`, and `police` on verified incoming edges. An opposing green keeps its 10-second minimum, then the installed 3-second yellow and 2-second all-red run before the emergency approach gets green. A compatible green can remain active past 45 seconds until the emergency vehicle leaves the junction. London Normal and Unbalanced support the separate experimental J3 cycle planner; emergency priority is not enabled there. `GET /api/simulation/status` includes `control_mode`, and adaptive snapshots include controller decision metadata. Reset retains the selected mode; stop returns to fixed.

For a visible emergency demo, select **Emergency priority demo** in the browser scenario list and press Start. The scenario contains three marked emergency vehicles. A headless run is:

```bash
python3 -m backend.simulation.runner --config scenarios/single_intersection/emergency.sumocfg --control-mode adaptive_with_emergency_priority
```

For a headless synthetic adaptive run: `python3 -m backend.simulation.runner --control-mode adaptive`. Every adaptive policy is a simulation experiment, not a validated traffic-signal controller. The J3 runtime manifest is checked against SUMO before commands are sent, but real pedestrian movements and real-world clearance remain unverified.

For a repeatable fixed/adaptive comparison and phase-safety audit, run `python3 -m backend.simulation.compare --scenario peak` (or `--scenario demo`). The script reports identical-demand metrics and exits nonzero on an unsafe phase trace, collision, teleport, or unfinished trip.

`POST /api/simulation/speed` changes pacing through the simulation worker while the service is `running` or `paused`; it does not restart SUMO or change vehicle physics. The response is the backend-confirmed status. Invalid values are rejected with HTTP 422, and invalid lifecycle states return HTTP 409.

Start defaults to `single_intersection`. The London selections are `london_normal`, `london_rush_hour`, and `london_unbalanced`. Reset restarts the active scenario; Stop closes SUMO and restores the synthetic default. London snapshots enumerate all active TLS controllers dynamically. The documented four deterministic J5 teleports in `london_rush_hour` are unchanged.

Snapshots contain worker-collected cumulative waiting metrics. Waiting vehicle-seconds are integrated once per SUMO step and retained after arrival; the live average uses every departed vehicle as its denominator. Live time loss is intentionally deferred to completed tripinfo analysis. Adaptive London mode is experimental and changes only J3 (`GS_26546583`) in Normal and Unbalanced; all other controllers remain fixed and Rush Hour rejects adaptive mode.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
