import { REPLAY_DATASET_IDS } from "@/lib/ai-replay";
import { proxyReplayRequest } from "@/lib/replay-api";

const DATASETS = new Set<string>(REPLAY_DATASET_IDS);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ dataset: string }> },
) {
  const { dataset } = await params;
  if (!DATASETS.has(dataset)) {
    return Response.json({ detail: "Unknown replay dataset" }, { status: 404 });
  }
  return proxyReplayRequest(`/api/ai-traffic/datasets/${encodeURIComponent(dataset)}/manifest`, request);
}
