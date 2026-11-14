import { proxyReplayRequest } from "@/lib/replay-api";

const ASSETS = new Set([
  "original_video",
  "annotated_video",
  "fixed_replay",
  "gap_v1_replay",
]);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ asset: string }> },
) {
  const { asset } = await params;
  if (!ASSETS.has(asset)) {
    return Response.json({ detail: "Unknown replay asset" }, { status: 404 });
  }
  return proxyReplayRequest(`/api/ai-traffic/assets/${encodeURIComponent(asset)}`, request);
}
