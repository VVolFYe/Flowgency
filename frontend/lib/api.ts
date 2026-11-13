import type { NetworkGeometry, SimulationSnapshot, SimulationStatus } from "./contracts";

export const BACKEND_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export const WS_URL = (() => {
  const url = new URL(BACKEND_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/simulation";
  url.search = "";
  return url.toString();
})();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BACKEND_URL}${path}`, { ...init, cache: "no-store", signal: init?.signal ?? AbortSignal.timeout(4000) });
  } catch {
    throw new Error(`Cannot reach the Flowgency backend at ${BACKEND_URL}`);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch { /* response was not JSON */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  network: () => request<NetworkGeometry>("/api/simulation/network"),
  status: () => request<SimulationStatus>("/api/simulation/status"),
  snapshot: async (): Promise<SimulationSnapshot | null> => {
    const response = await fetch(`${BACKEND_URL}/api/simulation/snapshot`, { cache: "no-store", signal: AbortSignal.timeout(4000) }).catch(() => null);
    if (!response) throw new Error(`Cannot reach the Flowgency backend at ${BACKEND_URL}`);
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Snapshot request failed (${response.status})`);
    return response.json() as Promise<SimulationSnapshot>;
  },
  command: (command: "start" | "pause" | "resume" | "reset" | "stop") =>
    request<SimulationStatus>(`/api/simulation/${command}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: command === "start" ? JSON.stringify({ simulation_speed: 4 }) : undefined,
    }),
};
