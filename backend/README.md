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
curl http://127.0.0.1:8000/api/simulation/network
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/pause
curl -X POST http://127.0.0.1:8000/api/simulation/resume \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/reset
curl -X POST http://127.0.0.1:8000/api/simulation/stop
```

Connect a WebSocket client to `ws://127.0.0.1:8000/ws/simulation`. Messages are envelopes with `type` equal to `status` or `snapshot` and a corresponding `data` object. The endpoint sends at most four messages per wall-clock second per client.

`GET /api/simulation/network` is a static, read-only response parsed once and cached from `demo.net.xml`; it neither starts SUMO nor accesses TraCI. It includes external and internal lane shapes, junction polygons, bounds, traffic-light IDs, and verified controlled-link mappings.

Geometry and vehicle positions use unchanged SUMO Cartesian metres with positive Y pointing upward. Browser canvas and many screen coordinate systems use positive Y downward. A frontend should use one shared transform for geometry and vehicles, for example `screen_y = viewport_height - (sumo_y - min_y) * scale`, and should not mutate API coordinates into latitude/longitude.

Development CORS is restricted to `http://localhost:3000` and `http://127.0.0.1:3000`; no wildcard origin is enabled.

`simulation_speed` means simulated seconds advanced per wall-clock second and accepts values from `0.1` through `100`. Reset starts a fresh SUMO process at time zero and leaves it paused. Stop releases SUMO and returns to `idle`.

`POST /api/simulation/start` also accepts `"control_mode": "fixed"` (default) or `"adaptive"`. Adaptive mode currently supports only the verified `single_intersection` scenario. It samples halting queues each simulated second, protects a 10-second minimum green, limits green to 45 seconds, starts the opposing transition after 40 seconds without green, smooths demand and requires three sustained samples before an early change. It only adjusts the remaining duration of the active green; the scenario's 3-second yellow and 2-second all-red phases stay in SUMO. `GET /api/simulation/status` includes `control_mode`, and adaptive snapshots include `control_reason`. Reset retains the selected mode; stop returns to fixed.

For a headless adaptive run: `python3 -m backend.simulation.runner --control-mode adaptive`. This policy is a simulation experiment, not a validated traffic-signal controller. London candidate mappings and pedestrian movements must be verified before extending it to that network.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
