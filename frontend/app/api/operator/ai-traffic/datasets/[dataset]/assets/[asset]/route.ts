import { REPLAY_DATASET_IDS } from "@/lib/ai-replay";
import { proxyReplayRequest } from "@/lib/replay-api";

const DATASETS = new Set<string>(REPLAY_DATASET_IDS);
const ASSETS = new Set([
  "original_video",
  "annotated_video",
  "fixed_replay",
  "gap_v1_replay",
]);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ dataset: string; asset: string }> },
) {
  const { dataset, asset } = await params;
  if (!DATASETS.has(dataset)) {
    return Response.json({ detail: "Unknown replay dataset" }, { status: 404 });
  }
  if (!ASSETS.has(asset)) {
    return Response.json({ detail: "Unknown replay asset" }, { status: 404 });
  }
  return proxyReplayRequest(
    `/api/ai-traffic/datasets/${encodeURIComponent(dataset)}/assets/${encodeURIComponent(asset)}`,
    request,
  );
}
