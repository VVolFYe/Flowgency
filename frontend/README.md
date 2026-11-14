# Flowgency frontend

Next.js control center for the server-owned SUMO simulation. The browser reads network geometry and live snapshots from FastAPI; it only interpolates received vehicle positions for display and never simulates traffic.

## Run

Start the backend from the repository root:

```bash
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

The simulation page loads its scenario list from the backend. Select the synthetic intersection or a London demand profile while the service is idle, then Start. The selected network uses actual SUMO Cartesian geometry; use the mouse wheel to zoom, drag to pan, and **Fit network** to restore the full extent. Scenario selection is locked during active and paused runs.

Control mode is selected before Start. **Emergency priority demo** defaults to `adaptive_with_emergency_priority` and highlights the declared ambulance, fire brigade, and police vehicles. London adaptive mode is intentionally limited to the audited J3 experimental controller in Normal and Unbalanced; Rush Hour remains fixed-only. Live metrics report cumulative vehicle-seconds waiting, average waiting per departed vehicle, arrivals, and current/maximum controlled-lane queues.

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
