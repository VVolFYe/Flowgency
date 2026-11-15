# Flowgency

Flowgency is an AI-assisted urban traffic management and simulation project for UniHack 2026. It will turn traffic-camera observations into simulation demand, use Eclipse SUMO to model a London road network, apply explainable adaptive signal control, prioritize detected emergency vehicles safely, and present live state and metrics in a browser.

> **Status:** the synthetic SUMO scenario, TraCI runner, simulation API/WebSocket, and a connected London baseline network are present. An adaptive controller for the synthetic scenario is in progress on `codex/adaptive-controller`. Frontend and vision remain unimplemented in this checkout.

## Problem and intended behavior

Fixed signal timing can respond poorly to changing congestion and can delay emergency vehicles. Flowgency will compare normal/adaptive control with deterministic emergency priority in simulation. Normal phase order, pedestrian clearance, yellow, all-red, minimum/maximum green, and anti-starvation constraints remain explicit. Emergency priority may interrupt the normal *sequence* after the current conflicting phase and required safety transitions finish; it never skips clearance intervals. This is a hackathon simulation, not a certified real-world controller.

Planned capabilities:

- derive observed vehicle counts and emergency detections from camera footage;
- translate observations into estimated demand without treating unseen approaches as zero;
- run one server-side SUMO network in left-hand traffic, beginning with one intersection;
- read queues, vehicles, and signal state and apply controller decisions through TraCI;
- stream simulation state to a custom web visualization; and
- compare waiting time, queues, throughput, and emergency delay.

## Selected London camera references

| ID | Location | TfL JamCam ID |
| --- | --- | --- |
| J1 | Camberwell New Rd / Brixton Rd (Oval) | `JamCams_00001.04503` |
| J2 | Camberwell New Rd / Vassall Rd | `JamCams_00001.04339` |
| J3 | Brixton Rd / Vassall Rd / Caldwell St | `JamCams_00001.04523` |
| J4 | Clapham Rd / Caldwell St | `JamCams_00001.04611` |
| J5 | Kennington Park Rd / Kennington Oval | `JamCams_00001.04345` |

These are camera references only. Their metadata, approach visibility, network geometry, and mapping to SUMO nodes and traffic-light IDs still require validation.

## Proposed stack

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS; later shadcn/ui, Lucide, Leaflet/OpenStreetMap, and Recharts.
- Backend: Python, FastAPI, Pydantic, and WebSockets.
- Simulation: Eclipse SUMO and Python TraCI.
- Vision: YOLO11, OpenCV, and tracking.
- Persistence: versioned JSON inputs and SUMO outputs. The one database is the analytics store for the Statistics page: the team's shared Postgres when `FLOWGENCY_ANALYTICS_DB` is set, otherwise a local, gitignored SQLite file (`data/analytics.sqlite3`). It holds a copy of the committed analytics JSON (the source of truth, loaded with `python -m backend.analytics.load`) and every simulation run started from the UI. See `backend/README.md`.

## Architecture and repository layout

The vision, controller, simulation, and UI components exchange versioned data contracts. Vision does not call SUMO, and controller policy does not depend on YOLO or browser concerns. One backend process can coordinate the MVP, with SUMO running as a child process and FastAPI serving state.

```text
frontend/              Next.js application (not scaffolded)
backend/
  api/                 HTTP and WebSocket boundary
  controller/          Pure control policy and emergency state machine
  simulation/          SUMO lifecycle and TraCI adapter
  vision/              Independent camera/CV pipeline
  models/              Shared Python schemas
scenarios/
  single_intersection/ First scenario assets
  london_network/      Later connected London network assets
docs/                  Architecture, contracts, and roadmap
tests/                 Future unit and integration tests
```

See [Architecture](docs/ARCHITECTURE.md), [Data contracts](docs/DATA_CONTRACTS.md), [Roadmap](docs/ROADMAP.md), and [Scenario guidance](scenarios/README.md).

## Development phases

Foundation is followed by a minimal SUMO intersection, adaptive control, API/web visualization, AI observation integration, emergency priority, a connected five-intersection London network, and analytics/demo hardening. Phases may overlap across team members; [the roadmap](docs/ROADMAP.md) identifies MVP and optional scope.

## Local prerequisites and setup status

Local development requires Linux/WSL, Python, Node.js/npm, and SUMO with Python TraCI support. The London network was generated with SUMO 1.27.1; Ubuntu 24.04's SUMO 1.18 package cannot load it. Follow the current [backend setup](backend/README.md) for a compatible virtual environment and the [frontend setup](frontend/README.md) for the browser application.

The repository is reached through a Linux symlink but physically resides on an NTFS-mounted Windows partition. Executable bits, ownership, case sensitivity, symlink behavior, file watching, and Unix sockets can differ from a native Linux filesystem. Avoid `chmod`/`chown`; if a Python virtual environment behaves poorly on NTFS, create it in a developer-owned Linux-native location outside the repository and keep only reproducible dependency manifests here.

## Portable AI Traffic demo setup

The prerecorded AI Traffic demo is versioned under
`assets/ai-traffic/versions/waiting-v1`. Its MP4 files use Git LFS. After
installing Git LFS for your operating system, populate the clone with:

```bash
git lfs install
git lfs pull
git lfs ls-files
```

Create the backend environment outside this NTFS checkout and install the
declared dependencies and matching SUMO toolchain:

```bash
python3 -m venv "$HOME/.venvs/flowgency"
source "$HOME/.venvs/flowgency/bin/activate"
python -m pip install -r backend/requirements.txt 'eclipse-sumo==1.27.1'
```

Install the pinned frontend dependencies:

```bash
cd frontend
npm ci
cd ..
```

Configure private Auth0 values without committing them. Copy
`frontend/.env.example` to the ignored `frontend/.env.local`, fill in
`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`,
`APP_BASE_URL`, and `AUTH0_AUDIENCE`, and export matching `AUTH0_DOMAIN` and
`AUTH0_AUDIENCE` in the backend shell. Follow [Auth0 setup](docs/AUTH0_SETUP.md)
for tenant roles, permissions, callbacks, and MFA. Do not place access tokens
or client secrets in source files.

Start the backend from the repository root, then start the frontend in another
terminal:

```bash
source "$HOME/.venvs/flowgency/bin/activate"
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"
python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm run dev
```

Sign in as an authorized operator and open
<http://localhost:3000/operator/ai-traffic>. No replay-directory setting is
needed for the committed bundle. Custom deployments can set
`FLOWGENCY_REPLAY_ASSET_DIR` in the backend process to override it with another
validated bundle.

## Collaboration

Four developers can own frontend, simulation/controller, API/integration, and vision while coordinating changes to `backend/models` and `docs/DATA_CONTRACTS.md`. Keep changes small; do not commit secrets, model weights, datasets, videos, caches, or generated simulation output; report only checks actually run. Repository-wide agent guidance is in [AGENTS.md](AGENTS.md).
