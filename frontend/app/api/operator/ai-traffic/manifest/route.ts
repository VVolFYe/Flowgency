import { proxyReplayRequest } from "@/lib/replay-api";

export async function GET(request: Request) {
  return proxyReplayRequest("/api/ai-traffic/manifest", request);
}
