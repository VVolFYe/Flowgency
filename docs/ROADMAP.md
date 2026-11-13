# Roadmap

Phases are dependency-aware, not strict team-wide gates; independent work may overlap when shared contracts remain stable.

## MVP phases

### Phase 0 — Repository foundation

Define boundaries, shared design contracts, scenario conventions, collaboration rules, and honest project status. **Exit:** documentation is consistent and required folders are tracked.

### Phase 1 — Minimal SUMO intersection

Create and validate one left-hand-traffic intersection, fixed safe signal plan, routes/demand, deterministic run command, and baseline output. Record project-to-SUMO mappings. **Exit:** repeatable SUMO run and inspectable baseline metrics.

**Status:** the Phase 1.1 synthetic single-intersection baseline is complete. London geometry and adaptive control remain later phases.

### Phase 2 — Adaptive controller

Implement a pure controller with configurable green bounds, congestion scoring, normal order, pedestrian/safety intervals, and anti-starvation. Add unit tests and a narrow TraCI adapter. **Exit:** adaptive and fixed modes run on the same scenario.

### Phase 3 — Backend API and web visualization

Scaffold FastAPI and Next.js; expose run controls and stream bounded snapshots. Render roads, vehicles, signals, queues, and connection state without browser-side physics. **Exit:** browser observes and controls a local simulation.

**Status:** the Phase 1.3 simulation service, REST lifecycle API, and bounded WebSocket stream are implemented; the frontend visualization remains pending.

### Phase 4 — AI traffic-observation integration

Implement/replay ingestion, detection/tracking, visible-approach counts, confidence, and observation-to-demand mapping. Keep media and weights out of Git. **Exit:** observations drive a repeatable scenario without coupling vision to TraCI.

### Phase 5 — Emergency priority

Implement deterministic request handling, compatible-green shortcut, safe clearance, expiry, simultaneous requests, and return to normal. **Exit:** tested scenarios demonstrate safe transitions and report emergency delay.

## Expansion and hardening

### Phase 6 — London multi-intersection network

Validate camera/network mappings and extend to one connected network containing about five intersections. Add cross-junction routes and test spillback. If time is limited, two connected intersections are a defensible fallback.

### Phase 7 — Analytics, testing, and demo

Compare fixed/adaptive/emergency modes using waiting time, queues, throughput, and emergency delay; harden failures; prepare a deterministic demo and setup guide. **Exit:** repeatable demo and honestly labeled results.

## Optional after the MVP

- live JamCam rather than recorded/replayed observations;
- polished landing page and richer map/chart interactions;
- scenario editor, persistent run history, or hosted deployment;
- advanced calibration or broader networks.

Reinforcement learning, a second physics engine, production infrastructure, and certified real-world control are out of scope.
