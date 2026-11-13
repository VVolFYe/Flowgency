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
