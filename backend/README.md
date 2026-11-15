# Flowgency backend

The Phase 1.3 backend runs one local SUMO process behind a dedicated simulation worker and exposes lifecycle controls through FastAPI. API and WebSocket code never calls TraCI directly.

## Dependencies

Create a virtual environment in a Linux-native developer directory outside this NTFS repository. Install the backend dependencies and the SUMO version used to generate the London network:

```bash
python3 -m venv "$HOME/.venvs/flowgency-sumo-1.27.1"
"$HOME/.venvs/flowgency-sumo-1.27.1/bin/python" -m pip install -r backend/requirements.txt 'eclipse-sumo==1.27.1'
```

The London network was generated with SUMO 1.27.1. Ubuntu 24.04's `apt` package
provides SUMO 1.18, which cannot load this network: it reports unknown vehicle
classes such as `scooter` and `drone`, then TraCI reports `Connection closed by
SUMO`. Check the active binary with `sumo --version`; use the virtual environment
above for both the SUMO binary and its matching Python tools.

## Run locally

From the repository root:

```bash
cp -n .env.example .env
cp -n backend/.env.example backend/.env
# Edit .env and set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID for voice audio.
# Edit backend/.env for Auth0, GEMINI_API_KEY (AI review) and, optionally, FLOWGENCY_ANALYTICS_DB (see below).
source "$HOME/.venvs/flowgency-sumo-1.27.1/bin/activate"
set -a; source .env; source backend/.env; set +a
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"
sumo --version  # Must report 1.27.1 for the London scenarios.
python3 -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

The backend reads these values from its process environment; it does not load
`.env` files automatically. The `source` step must run in the same shell that
starts Uvicorn. Both `.env` files are ignored by Git; the `.env.example` files
contain no credentials.

Useful requests:

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/simulation/status
curl http://127.0.0.1:8000/api/simulation/configuration-options
curl http://127.0.0.1:8000/api/simulation/network
curl 'http://127.0.0.1:8000/api/simulation/network?network=london'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"simulation_speed": 4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"network":"london","traffic_profile":"unbalanced","controller_mode":"fixed_timing","emergency_vehicles_enabled":false,"simulation_speed":4.0}'
curl -X POST http://127.0.0.1:8000/api/simulation/start \
  -H 'Content-Type: application/json' \
  -d '{"network":"london","traffic_profile":"unbalanced","controller_mode":"adaptive_network","emergency_vehicles_enabled":false,"simulation_speed":4.0}'
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

`GET /api/simulation/network` is static, read-only, cached per network, and never accesses TraCI. It accepts an explicit `network`; otherwise it follows the active configuration and defaults to `single_intersection` while idle. London geometry preserves UTM zone 30 projection metadata, external/internal lanes, junctions, TLS positions, and controlled links.

Geometry and vehicle positions use unchanged SUMO Cartesian metres with positive Y pointing upward. Browser canvas and many screen coordinate systems use positive Y downward. A frontend should use one shared transform for geometry and vehicles, for example `screen_y = viewport_height - (sumo_y - min_y) * scale`, and should not mutate API coordinates into latitude/longitude.

Development CORS is restricted to `http://localhost:3000` and `http://127.0.0.1:3000`; no wildcard origin is enabled.

`simulation_speed` means simulated seconds advanced per wall-clock second and accepts values from `0.1` through `100`. Reset starts a fresh SUMO process at time zero and leaves it paused. Stop releases SUMO and returns to `idle`.

`POST /api/simulation/start` accepts independent `network`, `traffic_profile`, `controller_mode`, and `emergency_vehicles_enabled` fields. Controller modes are `fixed_timing`, `adaptive_network`, and `adaptive_emergency_priority`. The verified synthetic adaptive policy samples halting queues each simulated second, protects a 10-second minimum green, and normally limits green to 45 seconds. Emergency priority recognizes declared SUMO emergency types on verified/controlled incoming lanes. It preserves minimum green and the installed yellow/all-red sequence. London Normal, Rush Hour, and Unbalanced use the experimental network profile and maintain priority state per traffic-light controller. `GET /api/simulation/status` exposes `active_configuration`; Reset retains it and Stop clears it.

For a visible emergency-priority run, select **Single Intersection**, enable **Emergency Vehicles**, choose **Adaptive Network + Emergency Priority**, and press Start. The emergency overlay contains two marked vehicles on conflicting approaches. A matching headless run is:

```bash
python3 -m backend.simulation.runner --config scenarios/single_intersection/normal_emergency.sumocfg --control-mode adaptive_with_emergency_priority
```

Traffic-triggered voice captions are included in simulation snapshots; no
scenario-selection, Start/Stop, or pause action triggers speech. The browser's
**Enable Voice Alerts** button requests MP3 audio from the backend only for new traffic
alerts. To test ElevenLabs, set `ELEVENLABS_API_KEY` and
`ELEVENLABS_VOICE_ID` in the backend process environment before starting
Uvicorn. Optional `ELEVENLABS_MODEL_ID` defaults to `eleven_multilingual_v2`;
`FLOWGENCY_VOICE_LANGUAGE=ro` selects Romanian captions and speech (English is
the default). Keep the API key out of the frontend and Git. Without these
settings, captions still work and audio requests return 503. See
[`docs/VOICE_ALERTS.md`](../docs/VOICE_ALERTS.md) for the exact triggers.

For a headless synthetic adaptive run: `python3 -m backend.simulation.runner --control-mode adaptive`. Every adaptive policy is a simulation experiment, not a validated traffic-signal controller. The J3 runtime manifest is checked against SUMO before commands are sent, but real pedestrian movements and real-world clearance remain unverified.

For a repeatable fixed/adaptive comparison and phase-safety audit, run `python3 -m backend.simulation.compare --scenario peak` (or `--scenario demo`). The script reports identical-demand metrics and exits nonzero on an unsafe phase trace, collision, teleport, or unfinished trip.

`POST /api/simulation/speed` changes pacing through the simulation worker while the service is `running` or `paused`; it does not restart SUMO or change vehicle physics. The response is the backend-confirmed status. Invalid values are rejected with HTTP 422, and invalid lifecycle states return HTTP 409.

Start defaults to Single Intersection + Normal + Fixed Timing + Emergency Vehicles Disabled. Reset restarts the active configuration; Stop closes SUMO and clears active state while the frontend keeps the editable selected configuration. London snapshots enumerate all active TLS controllers dynamically. Corrected Rush Hour routes completed the validated Fixed/Network Adaptive paired benchmark with 690 arrivals and no collisions or teleports in either mode.

Snapshots contain worker-collected cumulative waiting metrics. Waiting vehicle-seconds are integrated once per SUMO step and retained after arrival; the live average uses every departed vehicle as its denominator. Live time loss is intentionally deferred to completed tripinfo analysis. Adaptive London mode is experimental and uses the audited 22-controller network profile in Normal, Rush Hour, and Unbalanced. Emergency priority is available on both networks and is restricted to verified controlled traffic-light IDs.

## Analytics database (team Postgres or local SQLite)

The Statistics data (loaded analytics files and recorded simulation runs) lives in the database named by `FLOWGENCY_ANALYTICS_DB`:

- **Team Postgres (shared):** a `postgresql://` URL. Ask a teammate for it privately. It contains a password, so never send it through Git, issues or chat logs that end up in the repository.
- **Local SQLite (fallback):** if the variable is unset, the backend uses `data/analytics.sqlite3` in the repository (gitignored).

New teammates install the driver once with `pip install -r backend/requirements.txt` (it includes `psycopg[binary]`).

Linux/macOS: put the URL in `backend/.env` in **single quotes**. The file is read with `source`, which runs it as shell code, so an unquoted `&` or `$` in the URL or password would break the line:

```bash
FLOWGENCY_ANALYTICS_DB='postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
```

Then `set -a; source .env; source backend/.env; set +a` in the shell that runs the loader and Uvicorn.

Windows PowerShell (current session only):

```powershell
$env:FLOWGENCY_ANALYTICS_DB = 'postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require'
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
# Back to local SQLite: Remove-Item Env:FLOWGENCY_ANALYTICS_DB
```

Fill an empty database once with `python -m backend.analytics.load`. It creates the tables, then upserts `frontend/public/analytics/index.json`.

The Postgres database is shared by the whole team, so the Statistics page's "Last simulation" is the latest run recorded from **any** PC, and every teammate's runs land there. Each request opens its own connection, with a 5 s connect timeout. If the database is unreachable or not loaded, the analytics routes return 503. The URL is never logged or printed; the loader reports it as `hosted Postgres (URL hidden)`.

## Gemini AI review

`POST /api/analytics/insights` asks Gemini for a short review of the Statistics data. It requires an Auth0 token with `analytics:read` (the Next.js proxy `/api/analytics/insights` adds it) and the body `{"entry_id": null}` (latest recorded run plus, when both exist, the finished fixed/adaptive pair of its scenario) or `{"entry_id": "<analytics id>"}`. The backend reads the data from the analytics database itself and reduces time series, histograms and per-controller tables to summary statistics before prompting, so the browser never sends statistics. See DATA_CONTRACTS.md O.6.

Set in `backend/.env` (never commit it):

```bash
GEMINI_API_KEY=your-key            # required; https://aistudio.google.com/apikey
# GEMINI_MODEL=gemini-3.5-flash    # optional; this is the default
```

The key is read on every request, like `ELEVENLABS_API_KEY`. Results are cached in memory until the API restarts, keyed on the sha256 of the trimmed summary sent to Gemini plus the model, so repeated clicks on unchanged data do not spend quota and any data change asks Gemini again. One attempt with a 25 s timeout. Errors: 503 without `GEMINI_API_KEY`, without the `google-genai` package or without the database; 404 for no recorded run or an unknown id; 502 when Gemini fails or times out (for example `503 high demand`; try again or set another flash model in `GEMINI_MODEL`). The review is generated text about simulation output; check it against the numbers on the page.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```
