# Flowgency repository guidance

## Mission and scope

Flowgency is a 48-hour hackathon project that converts camera observations into estimated traffic demand, simulates traffic with Eclipse SUMO, applies deterministic adaptive and emergency-priority signal control, and streams simulation state to a web UI. Keep every change MVP-focused; this is a simulation platform, not a certified road controller.

## Architecture and ownership

- `frontend/`: Next.js browser UI and visualization. Consume API contracts; do not implement traffic physics or drive TraCI directly.
- `backend/api/`: FastAPI HTTP/WebSocket transport and orchestration boundary.
- `backend/controller/`: pure, explainable control algorithms and emergency state machine. Keep SUMO-specific calls behind the simulation adapter where practical.
- `backend/simulation/`: SUMO process lifecycle, TraCI, scenario loading, and state extraction.
- `backend/vision/`: independent camera ingestion, detection/tracking, and emergency detection. Emit shared observations; do not call SUMO directly.
- `backend/models/`: shared Python schemas. Contract changes also require an update to `docs/DATA_CONTRACTS.md`.
- `scenarios/`: version-controlled SUMO definitions and demand inputs. Generated runs belong in ignored output directories.
- `tests/`: controller/schema unit tests and narrowly scoped integration tests.

Coordinate before changing shared contracts or another developer's component. Prefer one backend deployment for the MVP over new services or infrastructure.

## Working rules

1. Read relevant code, documentation, and configuration before editing. Preserve useful behavior and follow existing conventions.
2. Make minimal, scoped changes; avoid unrelated refactors and unnecessary edits to another team member's area.
3. Keep frontend, vision, controller, and SUMO integration loosely coupled through explicit, versionable contracts.
4. Do not add a dependency without a concrete need and a short rationale. Avoid databases, queues, authentication, cloud infrastructure, and microservices unless accepted scope changes.
5. Never add secrets or API keys. Do not commit `.env` files, datasets, large videos, model weights, local caches, or generated SUMO logs/traces/metrics.
6. Treat unknown or unobserved traffic values as unknown; never silently convert them to zero. Distinguish observations, demand estimates, and simulated queues.
7. Preserve safe signal transitions: pedestrian clearance, yellow, all-red, configured green bounds, and anti-starvation behavior. Keep decisions deterministic and explainable; no reinforcement learning in the MVP.
8. Do not guess missing camera metadata, approach mappings, SUMO IDs, units, or prerequisites. Mark and report them explicitly.
9. Validate the smallest relevant surface, then run broader checks when risk warrants it. Report commands and failures honestly; do not claim runtime testing that was not performed.
10. Keep docs synchronized with architecture, setup, scenarios, and shared contract changes.

## Platform constraints

The repository may be accessed through a symlink while stored on NTFS. Avoid permission-only changes, case-only renames, repository-local Unix sockets, and assumptions about executable bits. Do not relocate the repository or alter mount configuration. A developer may keep a virtual environment in a Linux-native location, but reproducible manifests belong in the repository.
