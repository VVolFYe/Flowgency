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

`simulation_speed` means simulated seconds advanced per wall-clock second and accepts values from `0.1` through `100`. Reset starts a fresh SUMO process at time zero and leaves it paused. Stop releases SUMO and returns to `idle`.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
