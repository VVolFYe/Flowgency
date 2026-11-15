"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ReplayCanvas } from "@/components/ai-traffic/replay-canvas";
import {
  advancePlayback, assertManifestSelection, clampTime, createRequestSequencer,
  datasetManifestUrl, DEFAULT_REPLAY_DATASET_ID, defaultVideoSource, initialPlayback,
  isAnnotatedOnly, parseDatasetList, parseReplayJsonl, REPLAY_DATASET_IDS,
  REPLAY_DATASET_LABELS, REPLAY_DATASET_SHORT_LABELS, replayMetricsAtTime, replayTimelineDuration,
  switchVideoSource, validateReplayGeometry, videoDurationFor,
  videoTimeAtReplayTime, type AssetStatus, type MetricComparison,
  type ReplayDatasetId, type ReplayDatasetStatus, type ReplayManifest,
  type ReplayStream, type VideoSource,
} from "@/lib/ai-replay";
import { api } from "@/lib/api";
import type { NetworkGeometry } from "@/lib/contracts";

interface ReadyData { datasetId: ReplayDatasetId; manifest: ReplayManifest; geometry: NetworkGeometry; fixed: ReplayStream; gap: ReplayStream }
type LoadState = { kind: "loading"; message: string } | { kind: "ready"; data: ReadyData } | { kind: "error"; message: string };
type DatasetList = { kind: "loading" } | { kind: "ready"; datasets: ReplayDatasetStatus[] } | { kind: "error" };
const SPEEDS = [0.5, 1, 2, 4] as const;

function formatDuration(seconds: number | undefined | null) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60).toString().padStart(2, "0")}:${(whole % 60).toString().padStart(2, "0")}`;
}

async function replayText(asset: AssetStatus, label: string, signal: AbortSignal) {
  if (!asset.available || !asset.url) throw new Error(`${label} replay asset is unavailable`);
  const response = await fetch(asset.url, { cache: "no-store", signal });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `${label} replay request failed (${response.status})`);
  }
  return response.text();
}

function PanelState({ state, label }: { state: LoadState; label: string }) {
  const loading = state.kind === "loading";
  return <div className="grid h-full min-h-52 place-items-center px-6 py-10 text-center" role="status"><div className="max-w-xs"><span className={`mx-auto block h-2.5 w-2.5 rounded-full ${loading ? "pulse-soft bg-[#f1bd59]" : "bg-[#ff727b]"}`} /><p className="mt-4 text-sm font-semibold text-[#f5e9e0]">{loading ? state.message : `${label} unavailable`}</p><p className="mt-2 text-xs leading-5 text-[#c8b8ad]">{state.kind === "error" ? state.message : "Loading protected replay data and verified geometry."}</p></div></div>;
}

function ReplayPanel({ title, description, footer, children }: { title: string; description: string; footer: React.ReactNode; children: React.ReactNode }) {
  return <article className="overflow-hidden rounded-[20px] border border-white/[.1] bg-[#211712] shadow-xl shadow-black/20"><header className="min-h-24 border-b border-white/[.08] bg-[#2b1d16] px-5 py-4"><h2 className="text-base font-semibold text-[#fff4eb]">{title}</h2><p className="mt-1.5 text-xs leading-5 text-[#d1bfb2]">{description}</p></header><div className="aspect-video min-h-0 bg-[#0d0f10] xl:min-h-[300px]">{children}</div><footer className="flex min-h-12 items-center justify-between gap-3 border-t border-white/[.08] bg-[#17110e] px-5 py-3 text-xs text-[#d0beb2]">{footer}</footer></article>;
}

function MetricCard({ label, metric, suffix = "s" }: { label: string; metric?: MetricComparison; suffix?: string }) {
  return <article className="rounded-2xl border border-white/[.09] bg-[#211712] p-5 shadow-lg shadow-black/15"><p className="text-xs font-medium text-[#dfcbbd]">{label}</p><div className="mt-6 grid grid-cols-2 gap-3"><div><span className="text-[10px] uppercase tracking-wider text-[#a99486]">Fixed</span><strong className="mt-1 block font-mono text-xl font-medium text-[#fff4eb]">{metric ? `${metric.fixed.toLocaleString()}${suffix}` : "—"}</strong></div><div><span className="text-[10px] uppercase tracking-wider text-[#a99486]">gap_v1</span><strong className="mt-1 block font-mono text-xl font-medium text-[#fff4eb]">{metric ? `${metric.adaptive.toLocaleString()}${suffix}` : "—"}</strong></div></div><p className={`mt-4 border-t border-white/[.08] pt-3 text-xs ${metric?.outcome === "improvement" ? "text-[#91e7ae]" : metric?.outcome === "regression" ? "text-[#ff9ca3]" : "text-[#c8b8ad]"}`}>{metric ? `${metric.improvement_percent?.toFixed(3) ?? "—"}% ${metric.outcome}` : "Validated comparison unavailable"}</p></article>;
}

function DatasetOption({ datasetId, selected, status, listState, onSelect }: {
  datasetId: ReplayDatasetId;
  selected: boolean;
  status: ReplayDatasetStatus | undefined;
  listState: DatasetList["kind"];
  onSelect: (datasetId: ReplayDatasetId) => void;
}) {
  const badge = listState === "loading"
    ? { text: "Checking", tone: "border-[#f1bd59]/30 bg-[#f1bd59]/10 text-[#f1d18a]" }
    : !status
      ? { text: "Status unknown", tone: "border-white/15 bg-white/[.04] text-[#d2c0b4]" }
      : status.available
        ? { text: "Ready", tone: "border-[#7cf2ad]/30 bg-[#7cf2ad]/10 text-[#9cf5bd]" }
        : { text: "Not available", tone: "border-[#ff727b]/30 bg-[#ff727b]/10 text-[#ffb0b5]" };
  return <button type="button" role="radio" aria-checked={selected} onClick={() => onSelect(datasetId)} className={`flex min-w-0 flex-1 flex-col items-start gap-1.5 rounded-xl border px-4 py-3 text-left transition sm:min-w-[260px] ${selected ? "border-[#ffac79]/70 bg-[#3a2418] shadow-[0_0_0_1px_rgba(255,172,121,.25)]" : "border-white/[.1] bg-[#17110e] hover:border-[#ffac79]/40 hover:bg-[#2b1d16]"}`}><span className="flex w-full items-center justify-between gap-3"><span className="font-mono text-[10px] uppercase tracking-[.14em] text-[#cfb39f]">{REPLAY_DATASET_SHORT_LABELS[datasetId]}</span><span className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[9px] uppercase tracking-[.12em] ${badge.tone}`}>{badge.text}</span></span><span className={`text-sm font-semibold leading-5 ${selected ? "text-[#fff4eb]" : "text-[#ecdccf]"}`}>{REPLAY_DATASET_LABELS[datasetId]}</span><span className="text-xs leading-5 text-[#c9b6a9]">{status?.description || (datasetId === "demo2" ? "AI-annotated video only; no original footage was provided." : "Original and AI-annotated video.")}</span></button>;
}

export default function AiTrafficPage() {
  const [datasetId, setDatasetId] = useState<ReplayDatasetId>(DEFAULT_REPLAY_DATASET_ID);
  const [datasetList, setDatasetList] = useState<DatasetList>({ kind: "loading" });
  const [state, setState] = useState<LoadState>({ kind: "loading", message: "Loading replay manifest" });
  const [timeS, setTimeS] = useState(0);
  const timeRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [videoSource, setVideoSource] = useState<VideoSource>("annotated_video");
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoBuffering, setVideoBuffering] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const anchorRef = useRef({ wallMs: 0, replayS: 0 });
  const requests = useRef(createRequestSequencer());

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/operator/ai-traffic/datasets", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Dataset list request failed (${response.status})`);
        setDatasetList({ kind: "ready", datasets: parseDatasetList(await response.json()) });
      })
      .catch(() => { if (!controller.signal.aborted) setDatasetList({ kind: "error" }); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const token = requests.current.next();
    const controller = new AbortController();
    // Only the latest request for the currently selected dataset may update the page.
    const current = () => !controller.signal.aborted && requests.current.isCurrent(token);
    const label = REPLAY_DATASET_LABELS[datasetId];
    const load = async () => {
      try {
        const response = await fetch(datasetManifestUrl(datasetId), { cache: "no-store", signal: controller.signal });
        const value = await response.json().catch(() => null) as ReplayManifest | { detail?: string } | null;
        if (!response.ok) {
          const detail = value && "detail" in value ? value.detail : undefined;
          throw new Error(response.status === 503 || response.status === 404
            ? `${label} is not available${detail ? `: ${detail}` : ""}. Its replay bundle has not been generated or connected yet.`
            : detail ?? `Replay metadata request failed (${response.status})`);
        }
        const manifest = value as ReplayManifest;
        assertManifestSelection(manifest, datasetId);
        if (!current()) return;
        setState({ kind: "loading", message: `Loading ${label} network and replay streams` });
        const [geometry, fixedText, gapText] = await Promise.all([
          api.network("single_intersection", controller.signal),
          replayText(manifest.assets.fixed_replay, "Fixed", controller.signal),
          replayText(manifest.assets.gap_v1_replay, "gap_v1", controller.signal),
        ]);
        validateReplayGeometry(manifest, geometry);
        const fixed = parseReplayJsonl(fixedText, { frameCount: manifest.assets.fixed_replay.frame_count, durationS: manifest.replays.fixed.simulation_duration_s, coordinateSystem: manifest.network_geometry.coordinate_system, trafficLightId: "demo_01" });
        const gap = parseReplayJsonl(gapText, { frameCount: manifest.assets.gap_v1_replay.frame_count, durationS: manifest.replays.gap_v1.simulation_duration_s, coordinateSystem: manifest.network_geometry.coordinate_system, trafficLightId: "demo_01" });
        if (
          (manifest.assets.fixed_replay.waiting_series_available === true && !fixed.waitingSeriesAvailable) ||
          (manifest.assets.gap_v1_replay.waiting_series_available === true && !gap.waitingSeriesAvailable)
        ) throw new Error("Replay manifest declares missing waiting-time data");
        if (fixed.vehicleIds.size !== manifest.comparison.inputs.vehicle_count || gap.vehicleIds.size !== manifest.comparison.inputs.vehicle_count) throw new Error("Replay vehicle totals do not match the validated comparison");
        if (fixed.vehicleIds.size !== gap.vehicleIds.size || [...fixed.vehicleIds].some((id) => !gap.vehicleIds.has(id))) throw new Error("Fixed and gap_v1 replay vehicle identities differ");
        const source = defaultVideoSource(manifest);
        if (!current()) return;
        if (source) setVideoSource(source);
        setState({ kind: "ready", data: { datasetId, manifest, geometry, fixed, gap } });
      } catch (error) {
        if (current()) setState({ kind: "error", message: error instanceof Error ? error.message : "Replay data is unavailable" });
      }
    };
    void load();
    return () => controller.abort();
  }, [datasetId]);

  // Never render data from a previous dataset while another one is selected.
  const data = state.kind === "ready" && state.data.datasetId === datasetId ? state.data : null;
  const manifest = data?.manifest;
  const totalDurationS = data ? replayTimelineDuration(data.fixed, data.gap) : 0;
  const comparison = manifest?.comparison;
  const fixedCurrentMetrics = data ? replayMetricsAtTime(data.fixed, timeS) : null;
  const gapCurrentMetrics = data ? replayMetricsAtTime(data.gap, timeS) : null;
  const currentWaiting = fixedCurrentMetrics && gapCurrentMetrics
    ? { fixed: fixedCurrentMetrics, gap: gapCurrentMetrics }
    : null;
  const completedMetric: MetricComparison | undefined = comparison ? { fixed: comparison.runs.fixed.vehicle_count, adaptive: comparison.runs.adaptive.vehicle_count, adaptive_minus_fixed: 0, improvement_percent: 0, outcome: "no_change" } : undefined;
  const annotatedOnly = manifest ? isAnnotatedOnly(manifest) : datasetId === "demo2";

  useEffect(() => { timeRef.current = timeS; }, [timeS]);
  useEffect(() => {
    if (!playing || totalDurationS <= 0) return;
    anchorRef.current = { wallMs: performance.now(), replayS: timeRef.current };
    let animationFrame = 0;
    const update = (now: number) => {
      const next = advancePlayback(anchorRef.current.replayS, now - anchorRef.current.wallMs, speed, totalDurationS);
      timeRef.current = next;
      setTimeS(next);
      if (next >= totalDurationS) setPlaying(false);
      else animationFrame = requestAnimationFrame(update);
    };
    animationFrame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(animationFrame);
  }, [playing, speed, totalDurationS]);

  const seek = useCallback((nextTime: number) => {
    const clamped = clampTime(nextTime, totalDurationS);
    timeRef.current = clamped;
    setTimeS(clamped);
    anchorRef.current = { wallMs: performance.now(), replayS: clamped };
  }, [totalDurationS]);
  const pause = useCallback(() => {
    if (playing) {
      const anchor = anchorRef.current;
      seek(advancePlayback(anchor.replayS, performance.now() - anchor.wallMs, speed, totalDurationS));
    }
    setPlaying(false);
  }, [playing, seek, speed, totalDurationS]);
  const togglePlayback = () => {
    if (!data) return;
    if (playing) pause();
    else {
      if (timeRef.current >= totalDurationS) seek(0);
      anchorRef.current = { wallMs: performance.now(), replayS: timeRef.current };
      setPlaying(true);
    }
  };

  const selectDataset = (next: ReplayDatasetId) => {
    if (next === datasetId) return;
    // Pause, rewind to 0 and drop dataset-specific state before the new data loads.
    videoRef.current?.pause();
    const reset = initialPlayback();
    setPlaying(reset.playing);
    timeRef.current = reset.timeS;
    setTimeS(reset.timeS);
    anchorRef.current = { wallMs: performance.now(), replayS: reset.timeS };
    setVideoError(null);
    setVideoBuffering(false);
    setVideoSource("annotated_video");
    setState({ kind: "loading", message: `Loading ${REPLAY_DATASET_LABELS[next]}` });
    setDatasetId(next);
  };

  const selectedVideo = manifest?.assets[videoSource];
  const videoDuration = manifest ? videoDurationFor(manifest, videoSource) : undefined;
  const syncVideo = useCallback(() => {
    const video = videoRef.current;
    if (!video || videoDuration == null || !Number.isFinite(video.duration)) return;
    const desired = videoTimeAtReplayTime(timeRef.current, videoDuration);
    video.playbackRate = speed;
    if (Math.abs(video.currentTime - desired) > (playing ? 0.3 : 0.04)) video.currentTime = desired;
    if (playing && timeRef.current < videoDuration) {
      if (video.paused) void video.play().catch(() => setVideoError("The selected video could not start playback"));
    } else if (!video.paused) video.pause();
  }, [playing, speed, videoDuration]);
  useEffect(() => { syncVideo(); }, [syncVideo, timeS, videoSource]);
  const selectVideo = (source: VideoSource) => {
    if (source === videoSource || !manifest) return;
    const next = switchVideoSource(
      { source: videoSource, timeS: timeRef.current, playing },
      source,
      manifest.assets[source].available,
    );
    setVideoError(null);
    setVideoBuffering(false);
    setVideoSource(next.source);
  };

  const ready = Boolean(data);
  const videoEnded = videoDuration !== undefined && timeS >= videoDuration;
  const overallStatus = state.kind === "loading" ? "Loading" : state.kind === "error" ? "Error" : timeS >= totalDurationS ? "Complete" : playing ? "Playing" : "Paused";
  const headlineVideoDuration = manifest ? manifest.video.duration_s ?? manifest.video.annotated_duration_s : undefined;
  const datasetStatuses = datasetList.kind === "ready" ? datasetList.datasets : [];
  const originalAvailable = manifest?.assets.original_video.available === true;

  return <div>
    <div className="rounded-[24px] border border-white/[.08] bg-[#211712] p-6 shadow-xl shadow-black/20"><div className="flex flex-wrap items-end justify-between gap-5"><div><p className="eyebrow">Recorded traffic experiment</p><h1 className="mt-2 text-4xl font-semibold tracking-[-.045em]">AI Traffic</h1><p className="mt-3 max-w-3xl text-sm leading-6 text-[#dcc8ba]">Compare protected recorded footage with synchronized Fixed and runtime-verified gap_v1 SUMO trajectories. Playback uses recorded data and never starts the live simulation worker.</p></div><div className={`rounded-full border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[.14em] ${state.kind === "ready" ? "border-[#7cf2ad]/30 bg-[#7cf2ad]/10 text-[#9cf5bd]" : state.kind === "error" ? "border-[#ff727b]/30 bg-[#ff727b]/10 text-[#ffb0b5]" : "border-[#f1bd59]/30 bg-[#f1bd59]/10 text-[#f1d18a]"}`}>{overallStatus}</div></div>
      <div className="mt-5 border-t border-white/[.08] pt-4">
        <p id="dataset-heading" className="text-xs font-semibold uppercase tracking-[.14em] text-[#d6c3b6]">Intersection</p>
        <div role="radiogroup" aria-labelledby="dataset-heading" className="mt-3 flex flex-col gap-3 sm:flex-row">
          {REPLAY_DATASET_IDS.map((id) => <DatasetOption key={id} datasetId={id} selected={id === datasetId} status={datasetStatuses.find((item) => item.dataset_id === id)} listState={datasetList.kind} onSelect={selectDataset} />)}
        </div>
        <div className="mt-4"><h2 className="text-base font-semibold text-[#fff1e7]">{REPLAY_DATASET_LABELS[datasetId]}</h2>{manifest?.display_name && <p className="mt-0.5 text-xs text-[#d6c3b6]">{manifest.display_name}</p>}<p className="mt-1 text-xs text-[#c7b4a7]">{manifest ? `${formatDuration(headlineVideoDuration)} ${manifest.video.duration_s == null ? "AI-annotated video" : "source video"} · ${formatDuration(totalDurationS)} replay · ${comparison?.inputs.vehicle_count ?? "—"} vehicles · camera orientation unverified` : state.kind === "error" ? "Replay bundle unavailable for this dataset" : "Loading protected replay manifest"}</p></div>
      </div>
    </div>
    {state.kind === "error" && <div role="alert" className="mt-4 rounded-xl border border-[#ff727b]/30 bg-[#2a1314] px-4 py-3 text-sm text-[#ffc0c4]">{state.message}</div>}

    <section className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Synchronized replay panels">
      <ReplayPanel title={annotatedOnly ? "AI-detected video" : "Original / AI-detected video"} description={annotatedOnly ? "Only the AI-annotated recording was provided for this dataset. No unannotated original footage exists." : "Switch between protected source footage and the computer-vision overlay."} footer={<><span>{videoError ? "Video error" : videoBuffering ? "Buffering · all panels paused" : videoEnded ? "Video ended" : playing ? "Playing" : "Paused"}</span><span className="font-mono text-[#f0d6c3]">{formatDuration(videoTimeAtReplayTime(timeS, videoDuration ?? 0))}</span></>}>
        {ready && selectedVideo?.available && selectedVideo.url ? <div className="relative h-full w-full bg-black"><video ref={videoRef} key={`${datasetId}-${videoSource}`} src={selectedVideo.url} preload="auto" muted playsInline className="h-full w-full object-contain" aria-label={videoSource === "original_video" ? "Original traffic video" : "AI-annotated traffic video"} onLoadedMetadata={() => { setVideoError(null); syncVideo(); }} onCanPlay={() => setVideoBuffering(false)} onWaiting={() => { if (timeRef.current < (videoDuration ?? 0)) { setVideoBuffering(true); pause(); } }} onError={() => { setVideoError("The selected protected video could not be loaded"); pause(); }} /><div className="absolute left-3 top-3 flex items-center rounded-lg border border-white/10 bg-black/75 p-1 backdrop-blur"><button type="button" onClick={() => selectVideo("original_video")} disabled={!originalAvailable} aria-pressed={videoSource === "original_video"} title={originalAvailable ? undefined : "No original footage was provided for this dataset"} className={`rounded-md px-2.5 py-1.5 text-[10px] font-medium disabled:cursor-not-allowed disabled:opacity-45 ${videoSource === "original_video" ? "bg-white/15 text-white" : "text-[#c9bab0] hover:bg-white/10"}`}>Original</button><button type="button" onClick={() => selectVideo("annotated_video")} disabled={!manifest?.assets.annotated_video.available} aria-pressed={videoSource === "annotated_video"} className={`rounded-md px-2.5 py-1.5 text-[10px] font-medium ${videoSource === "annotated_video" ? "bg-white/15 text-white" : "text-[#c9bab0] hover:bg-white/10"}`}>AI annotated</button>{!originalAvailable && <span className="px-2 text-[10px] text-[#d8c6b9]">Original not provided</span>}</div>{videoEnded && <div className="absolute bottom-3 right-3 rounded-full border border-[#7cf2ad]/30 bg-[#11291c]/90 px-2.5 py-1 text-[10px] font-medium text-[#a2f4be]">Video ended</div>}{videoError && <div role="alert" className="absolute inset-x-3 bottom-3 rounded-lg border border-[#ff727b]/30 bg-[#2a1314]/95 px-3 py-2 text-xs text-[#ffc0c4]">{videoError}</div>}</div> : <PanelState state={state} label="Video" />}
      </ReplayPanel>
      <ReplayPanel title="Fixed SUMO simulation" description="Recorded trajectories from the unchanged fixed traffic-light program." footer={<><span>{data ? timeS >= data.fixed.durationS ? "Simulation finished" : playing ? "Playing" : "Paused" : "Replay unavailable"}</span><span className="font-mono text-[#f0d6c3]">{manifest?.assets.fixed_replay.frame_count ?? "—"} frames</span></>}>
        {data ? <ReplayCanvas key={`${datasetId}-fixed`} geometry={data.geometry} replay={data.fixed} timeS={timeS} playing={playing} accent="#dce9ef" /> : <PanelState state={state} label="Fixed replay" />}
      </ReplayPanel>
      <ReplayPanel title="Adaptive gap_v1 SUMO simulation" description="Recorded trajectories using verified gap_v1 control at demo_01." footer={<><span>{data ? timeS >= data.gap.durationS ? "Simulation finished" : playing ? "Playing" : "Paused" : "Replay unavailable"}</span><span className="font-mono text-[#f0d6c3]">{manifest?.assets.gap_v1_replay.frame_count ?? "—"} frames</span></>}>
        {data ? <ReplayCanvas key={`${datasetId}-gap`} geometry={data.geometry} replay={data.gap} timeS={timeS} playing={playing} accent="#7de7ff" /> : <PanelState state={state} label="gap_v1 replay" />}
      </ReplayPanel>
    </section>

    <section className="mt-4 rounded-[20px] border border-white/[.09] bg-[#17110e] p-5 shadow-lg shadow-black/15" aria-labelledby="live-waiting-heading">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Recorded at replay time</p><h2 id="live-waiting-heading" className="mt-2 text-lg font-semibold text-[#fff4eb]">Cumulative waiting so far</h2></div><span className="font-mono text-xs text-[#d6c3b6]">t = {formatDuration(timeS)}</span></div>
      {currentWaiting ? <div className="mt-4 grid gap-3 md:grid-cols-2">
        <article className="rounded-2xl border border-white/[.09] bg-[#211712] p-5"><p className="text-xs font-medium uppercase tracking-[.12em] text-[#b8a69a]">Fixed</p><p className="mt-3 font-mono text-3xl font-semibold text-[#fff4eb]">{currentWaiting.fixed.cumulative_waiting_time_s.toLocaleString()} <span className="text-base font-normal text-[#c9b8ad]">seconds</span></p><p className="mt-3 text-xs text-[#c8b6aa]">{currentWaiting.fixed.active_vehicle_count} active · {currentWaiting.fixed.arrived_vehicle_count} completed · final validated total {comparison?.runs.fixed.total_waiting_time_s.toLocaleString() ?? "—"}s</p></article>
        <article className="rounded-2xl border border-[#7de7ff]/20 bg-[#172126] p-5"><p className="text-xs font-medium uppercase tracking-[.12em] text-[#9fcbd5]">Adaptive gap_v1</p><p className="mt-3 font-mono text-3xl font-semibold text-[#dff9ff]">{currentWaiting.gap.cumulative_waiting_time_s.toLocaleString()} <span className="text-base font-normal text-[#b7d4da]">seconds</span></p><p className="mt-3 text-xs text-[#b8cbd0]">{currentWaiting.gap.active_vehicle_count} active · {currentWaiting.gap.arrived_vehicle_count} completed · final validated total {comparison?.runs.adaptive.total_waiting_time_s.toLocaleString() ?? "—"}s</p></article>
        <p className="md:col-span-2 rounded-xl border border-white/[.08] bg-[#211712] px-4 py-3 text-xs text-[#d6c3b6]">Current Fixed − gap_v1 difference: <strong className="font-mono text-[#fff4eb]">{(currentWaiting.fixed.cumulative_waiting_time_s - currentWaiting.gap.cumulative_waiting_time_s).toLocaleString()}s</strong>. Values are recorded SUMO vehicle-seconds at the selected timestamp, not interpolated from final totals.</p>
      </div> : data ? <div className="mt-4 rounded-xl border border-[#f1bd59]/25 bg-[#2a2113] px-4 py-4 text-sm text-[#f1d18a]">Cumulative waiting-time series is unavailable in this replay version. Regenerate the replay with metrics recording; no intermediate values have been fabricated.</div> : <div className="mt-4 rounded-xl border border-white/[.08] bg-[#211712] px-4 py-4 text-sm text-[#d6c3b6]">{state.kind === "error" ? "No recorded waiting-time series is available for this dataset." : "Loading the recorded waiting-time series for this dataset."}</div>}
    </section>

    <section className="mt-4 rounded-[20px] border border-white/[.09] bg-[#211712] p-5 shadow-lg shadow-black/15" aria-labelledby="playback-heading"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 id="playback-heading" className="text-base font-medium text-[#fff4eb]">Shared playback</h2><p className="mt-1 text-xs text-[#c8b6aa]">One monotonic clock drives video, Fixed and gap_v1. Video freezes at its final frame while simulations continue.</p></div><span className="font-mono text-xs text-[#ead1c0]">{formatDuration(timeS)} / {formatDuration(totalDurationS)}</span></div><div className="mt-5 grid gap-4 lg:grid-cols-[auto_minmax(180px,1fr)_160px] lg:items-end"><div className="flex gap-2"><button type="button" disabled={!ready} onClick={togglePlayback} className="rounded-xl border border-white/[.12] bg-[#17110e] px-4 py-2.5 text-sm text-[#f5e9e0] transition hover:bg-[#2b1d16] disabled:cursor-not-allowed disabled:opacity-45">{playing ? "Pause" : timeS >= totalDurationS && ready ? "Replay" : "Play"}</button><button type="button" disabled={!ready} onClick={() => { pause(); seek(0); }} className="rounded-xl border border-white/[.12] bg-[#17110e] px-4 py-2.5 text-sm text-[#f5e9e0] transition hover:bg-[#2b1d16] disabled:cursor-not-allowed disabled:opacity-45">Restart</button></div><label><span className="mb-2 block text-xs text-[#d0bdb0]">Timeline</span><input type="range" min="0" max={totalDurationS || 1} step="0.1" value={timeS} disabled={!ready} onChange={(event) => seek(Number(event.target.value))} aria-label="Shared replay timeline" className="w-full accent-[#ffac79] disabled:cursor-not-allowed disabled:opacity-45" /></label><label><span className="mb-2 block text-xs text-[#d0bdb0]">Playback speed</span><select value={speed} disabled={!ready} onChange={(event) => setSpeed(Number(event.target.value) as (typeof SPEEDS)[number])} className="w-full rounded-xl border border-white/[.1] bg-[#17110e] px-3 py-2.5 text-sm text-[#f0dfd4] disabled:cursor-not-allowed disabled:opacity-45">{SPEEDS.map((option) => <option key={option} value={option}>{option}×</option>)}</select></label></div></section>

    <section className="mt-4 rounded-[20px] border border-white/[.09] bg-[#17110e] p-5 sm:p-6" aria-labelledby="comparison-heading"><div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">Validated report</p><h2 id="comparison-heading" className="mt-2 text-xl font-semibold text-[#fff4eb]">Fixed vs gap_v1 metrics</h2></div><p className="text-xs text-[#c8b6aa]">{comparison ? `${comparison.inputs.vehicle_count} matching completed vehicles · ${comparison.validation.collisions} collisions · ${comparison.validation.teleports} teleports` : "Comparison report unavailable"}</p></div><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Total waiting time" metric={comparison?.comparison.total_waiting_time_s} /><MetricCard label="Total time loss" metric={comparison?.comparison.total_time_loss_s} /><MetricCard label="Total insertion delay" metric={comparison?.comparison.total_insertion_delay_s} /><MetricCard label="Completed vehicles" metric={completedMetric} suffix="" /></div><p className="mt-4 rounded-xl border border-white/[.08] bg-[#211712] px-4 py-3 text-xs leading-5 text-[#d6c3b6]">Metrics come from the externally stored, strictly validated comparison report. They are historical experiment results—not live calculations or claims about real-world traffic performance.</p>{manifest && manifest.limitations.length > 0 && <div className="mt-3 rounded-xl border border-white/[.08] bg-[#211712] px-4 py-3"><p className="text-xs font-semibold text-[#ecdccf]">Dataset limitations</p><ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-[#d6c3b6]">{manifest.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>}</section>
  </div>;
}
