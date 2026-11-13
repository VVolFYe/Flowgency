# Architecture

## Design goals and flow

Flowgency starts with one functioning intersection, then extends the same server-side SUMO simulation to a connected network of approximately five London intersections. It favors explicit contracts, deterministic behavior, and parallel work by four developers over production-scale infrastructure.

```text
camera/video -> vision -> traffic observation -> demand mapping -> SUMO
                                                               |
SUMO --TraCI--> simulation state -> controller --TraCI---------+
  |
  +-> API/WebSocket -> browser map, signal view, and charts
  +-> SUMO output -> offline metrics and scenario comparison
```

1. `backend/vision` emits camera-grounded observations. A demand-mapping step converts visible counts into estimated arrivals or trips while retaining uncertainty and approach coverage.
2. `backend/simulation` advances SUMO, extracts queues/signals/vehicles through TraCI, asks `backend/controller` for a decision, validates it against scenario capabilities, and applies it through TraCI.
3. `backend/api` publishes bounded state snapshots over WebSocket. The frontend may interpolate for display but does not simulate traffic or become the source of truth.
4. SUMO output and controller event logs are aggregated into comparable scenario metrics.

## Component responsibilities

### Frontend

The Next.js App Router application will provide Dashboard, Simulation Lab, and Analytics views. It owns presentation, connection state, and user inputs and labels simulated data clearly.

### API

FastAPI owns HTTP commands, WebSocket lifecycle, serialization, and orchestration. Initially it may run alongside one simulation worker in one local deployment. It exposes shared schemas, not raw TraCI objects, and should coalesce snapshots if clients cannot keep up.

### Controller

The controller consumes normalized intersection state and configuration and returns a decision. Its core remains pure Python so timing rules can be tested without SUMO.

Normal mode preserves configured phase ordering. It varies green allocation within minimum/maximum bounds based on congestion, honors compatible pedestrian phases and safety timings, and prevents starvation.

Emergency mode maintains a deterministic request queue (proposed ordering: active compatible request first, then event timestamp, then stable event ID). If an approach already has compatible green, it avoids switching. Otherwise, the current conflicting phase finishes; pedestrian clearance, yellow, and all-red complete; then control transitions directly to an emergency-compatible phase without waiting for the rest of the normal cycle. Expired requests are removed. After service, the state machine returns safely to normal adaptive control. Phase completion, conflicts, timeout, and recovery must be scenario-configured and tested.

### Simulation

This module owns the SUMO process and TraCI connection, stepping, subscriptions/state reads, signal command application, coordinate conversion, and output collection. It maps stable project IDs to verified SUMO IDs. SUMO remains the only traffic physics engine.

### Vision

Vision owns camera ingestion, YOLO11 detection, tracking, visible-approach aggregation, confidence, and possible emergency-light detection. It emits shared observations and runs independently of SUMO. Recorded input is preferable for a reliable demo; live TfL access remains open.

### Shared models

`backend/models` will define Pydantic forms of `DATA_CONTRACTS.md`. Transport schemas contain no YOLO tensors, OpenCV frames, TraCI objects, or frontend state.

## Why SUMO is server-side

TraCI controls an authoritative, step-based native SUMO process unavailable in the browser. Server-side ownership avoids duplicate JavaScript physics, centralizes lifecycle and metrics, and gives every client one consistent state. The browser receives visualization snapshots only.

## Real observations versus simulation

An **observed count** is camera evidence for a visible approach and time window. **Estimated demand** is a modeled input derived from evidence and assumptions. A **simulated queue** is a SUMO outcome. They differ in uncertainty, units, and time basis and must not be presented interchangeably. Occluded approaches are not zero, and simulation is not an exact reconstruction of reality.

## From one intersection to five

Phase 1 validates the complete loop with one intersection and stable IDs. Expansion reuses contracts and one controller instance per intersection, but runs one connected left-hand-traffic SUMO network so routes, spillback, and travel times cross junction boundaries. Each intersection needs explicit mappings for project IDs, approaches, movements, signal phases, pedestrian compatibility, and SUMO traffic-light/link IDs. J1–J5 camera proximity alone does not establish those mappings.

## Local deployment and constraints

For the MVP, one FastAPI application coordinates one local SUMO process; the frontend runs separately in development. Vision may write/replay contract JSON or call a later ingestion endpoint. Redis, a database, containers, and cloud services are not required.

The NTFS-backed repository may differ in executable bits, ownership, symlinks, case sensitivity, file watching, and Unix sockets. Invoke scripts through interpreters, avoid permission churn, and consider developer-local Linux-native virtual environments while keeping manifests and source here.

## Limitations and open decisions

- Verify JamCam metadata, licensing/access, view direction, coverage, and timestamps.
- Select the first junction after confirming geometry and signals; J1 is not yet a validated SUMO junction.
- Later choose a small hand-built network or OSM import; neither belongs to Phase 0.
- Verify traffic-light/link IDs, conflicts, pedestrian phases, and left-hand connections in NetEdit.
- Define observation-to-demand calibration, unobserved-approach behavior, snapshot rate, coordinate transform, and replay format.
- Define phase completion, emergency expiry/service, simultaneous-request policy, and safe recovery.
- Validate Python 3.14 compatibility with future CV/Pydantic packages before choosing a project version.
- Choose SUMO outputs for final metrics and define handling of unfinished trips.
