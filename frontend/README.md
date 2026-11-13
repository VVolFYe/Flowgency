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

Open <http://localhost:3000/simulation>. Port 3000 is required by the backend's development CORS policy.

The simulation page loads its scenario list from the backend. Select the synthetic intersection or a London demand profile while the service is idle, then Start. The selected network uses actual SUMO Cartesian geometry; use the mouse wheel to zoom, drag to pan, and **Fit network** to restore the full extent. Scenario selection is locked during active and paused runs.

Fixed/adaptive mode is selected before Start. London adaptive mode is intentionally limited to the audited J3 experimental controller in Normal and Unbalanced; Rush Hour remains fixed-only. Live metrics report cumulative vehicle-seconds waiting, average waiting per departed vehicle, arrivals, and current/maximum controlled-lane queues.

Road geometry is drawn on a static canvas layer while live SUMO vehicles and signal lamps use a separate animation layer. London lamps are positioned at the end of their actual controlled incoming lanes and read the character at each connection's SUMO link index; they never reduce a mixed controller state to one color. Hover a lamp for its controller, link index, state semantics, lane, destination, and movement. Neutral controller markers remain as a fallback before live state is available.

The backend defaults to `http://127.0.0.1:8000`. To use another address, copy `.env.example` to `.env.local` and set:

```bash
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```

The WebSocket URL is derived automatically using `ws:` or `wss:`. Do not commit `.env.local`.

## Checks

```bash
npm run lint
npm run typecheck
npm run build
```
