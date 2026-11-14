# Flowgency frontend

Next.js control center for the server-owned SUMO simulation. The browser reads network geometry and live snapshots from FastAPI; it only interpolates received vehicle positions for display and never simulates traffic.

## Run

Start the backend from the repository root (details, Windows commands and the analytics database setup are in `backend/README.md`):

```bash
set -a; source .env; source backend/.env; set +a   # FLOWGENCY_ANALYTICS_DB unset = local SQLite
python3 -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Then start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Node.js 22 or newer is required by the pinned frontend toolchain.

Open <http://localhost:3000>. Port 3000 is required by the backend's development CORS policy.

The Operator simulation page loads four independent selectors from the backend: Map / Network, Traffic Profile, Controller Mode, and Emergency Vehicles. All selectors lock during an active or paused run and the backend-confirmed Active configuration replaces the pre-start Selected configuration. The selected network uses actual SUMO Cartesian geometry; use the mouse wheel to zoom, drag to pan, and **Fit network** to restore the full extent.

Controller mode is selected before Start. Emergency Vehicles is independent: Fixed Timing and Adaptive Network still load and display ambulances but do not grant signal preemption. Adaptive Network + Emergency Priority composes deterministic per-intersection emergency handling with adaptive control. London adaptive mode uses the audited experimental network profile in Normal, Rush Hour, and Unbalanced. Live metrics report cumulative vehicle-seconds waiting, average waiting per departed vehicle, arrivals, and current/maximum controlled-lane queues.

The simulation view also displays traffic alert captions. Click **Enable voice**
to hear new alerts through the backend's optional ElevenLabs integration; the
button itself and simulation controls do not speak. Backend credentials and
message triggers are documented in [`docs/VOICE_ALERTS.md`](../docs/VOICE_ALERTS.md).

Road geometry is drawn on a static canvas layer while live SUMO vehicles and signal lamps use a separate animation layer. London lamps are positioned at the end of their actual controlled incoming lanes and read the character at each connection's SUMO link index; they never reduce a mixed controller state to one color. Hover a lamp for its controller, link index, state semantics, lane, destination, and movement. Neutral controller markers remain as a fallback before live state is available.

The backend defaults to `http://127.0.0.1:8000`. To use another address, copy `.env.example` to `.env.local` and set:

```bash
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```

The WebSocket URL is derived automatically using `ws:` or `wss:`. Do not commit `.env.local`.

## Public and Operator access

The public site is read-only:

- `/` — Flowgency introduction
- `/simulation` — live geometry, vehicles, signals, connection state, simulation time, and vehicle count

The Operator area is protected by a server-validated, signed `HttpOnly` cookie:

- `/operator/login` — Operator login
- `/operator` — operational overview
- `/operator/simulation` — full simulation controls and snapshot details
- `/operator/analytics` — live charts for the current browser session

Copy `.env.example` to `.env.local` and replace all demo Operator values:

```bash
OPERATOR_USERNAME=operator
OPERATOR_PASSWORD=use-a-local-demo-password
OPERATOR_SESSION_SECRET=use-a-long-random-secret
```

These variables are server-only. Never rename them with a `NEXT_PUBLIC_` prefix. The session lasts eight hours, is marked `Secure` in production, and can be ended with Logout. This demo authentication intentionally has no account registration or user administration.

Analytics uses only live snapshot fields. If the backend provides no historical endpoint, snapshots are retained in browser `sessionStorage`, labeled `Current browser session`, and reset when `run_id` changes. Missing values remain `—`.

## Checks

```bash
npm run lint
npm run typecheck
npm run build
```

For an end-to-end local check, start `npm run dev`, visit the public routes, then verify that opening `/operator` in a signed-out browser redirects to `/operator/login`. Sign in with the local environment credentials, exercise the controls, inspect Analytics, and use Logout.

## Road-map presentation

Simulation views default to a MapLibre road map, with a Technical switch for the SUMO canvas. London uses the public OpenFreeMap Liberty style with its OpenStreetMap attribution. Its tiles, fonts and sprites require internet access. The technical canvas stays available when those resources or WebGL are unavailable.

The synthetic intersection uses a local engineering scene with illustrative buildings, explicitly labeled in the view. Its surroundings are decoration. Road shapes, signal states, vehicle positions and headings come from the existing SUMO geometry and snapshots. Geographic positions for London use the supplied projection and subtract SUMO's net offset before conversion with proj4. No real-world location is assigned to the synthetic scene.

The map supports top-down/tilted views, fit-to-network, zoom, signal tooltips and vehicle details. Click a vehicle and choose Follow vehicle to center the camera on it. Dragging the map, fitting the network or Stop following releases the camera. Cars, buses, ambulances, police and fire vehicles use locally generated icons. New runs reset interpolation.

Dependencies: maplibre-gl supplies vector-map/WebGL rendering and camera controls; proj4 converts the supplied SUMO projection without changing the API contract. The worker asset is referenced explicitly through Next.js so it is bundled locally in development and production.
