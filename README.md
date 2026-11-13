# Flowgency

Flowgency is an AI-assisted urban traffic management and simulation project for UniHack 2026. It will turn traffic-camera observations into simulation demand, use Eclipse SUMO to model a London road network, apply explainable adaptive signal control, prioritize detected emergency vehicles safely, and present live state and metrics in a browser.

> **Status:** Phase 0 repository foundation. No frontend, API, controller, vision pipeline, or SUMO scenario is implemented yet.

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
- Persistence: versioned JSON inputs and SUMO outputs initially; no database is required for the MVP.

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

Eventually, development will require Linux/WSL, Python, Node.js/npm, and SUMO with Python TraCI support. SUMO 1.27.1 is available on the current machine and must not be reinstalled for this phase. Exact supported Python/Node versions and setup commands will be added when manifests exist; there are currently no dependencies to install or applications to run.

The repository is reached through a Linux symlink but physically resides on an NTFS-mounted Windows partition. Executable bits, ownership, case sensitivity, symlink behavior, file watching, and Unix sockets can differ from a native Linux filesystem. Avoid `chmod`/`chown`; if a Python virtual environment behaves poorly on NTFS, create it in a developer-owned Linux-native location outside the repository and keep only reproducible dependency manifests here.

## Collaboration

Four developers can own frontend, simulation/controller, API/integration, and vision while coordinating changes to `backend/models` and `docs/DATA_CONTRACTS.md`. Keep changes small; do not commit secrets, model weights, datasets, videos, caches, or generated simulation output; report only checks actually run. Repository-wide agent guidance is in [AGENTS.md](AGENTS.md).
