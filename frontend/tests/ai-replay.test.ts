import assert from "node:assert/strict";
import {
  advancePlayback,
  assertManifestSelection,
  availableVideoSources,
  createRequestSequencer,
  datasetManifestUrl,
  DEFAULT_REPLAY_DATASET_ID,
  defaultVideoSource,
  frameAtTime,
  initialPlayback,
  isAnnotatedOnly,
  isReplayDatasetId,
  parseDatasetList,
  parseReplayJsonl,
  REPLAY_DATASET_IDS,
  REPLAY_DATASET_LABELS,
  replayTimelineDuration,
  videoDurationFor,
  type ReplayManifest,
  replaySignalColor,
  replayMetricsAtTime,
  sourceStatus,
  switchVideoSource,
  videoTimeAtReplayTime,
} from "../lib/ai-replay.ts";

const vehicle = (id: string, x: number) => ({
  vehicle_id: id,
  x_m: x,
  y_m: 20,
  angle_deg: x === 0 ? 350 : 10,
  speed_mps: 5,
  lane_id: "south_in_0",
  edge_id: "south_in",
});

const frame = (
  index: number,
  vehicles: ReturnType<typeof vehicle>[],
  state = "GrGr",
  waiting?: number,
) => JSON.stringify({
  schema_version: "1.0",
  record_type: "frame",
  frame_index: index,
  simulation_time_s: index,
  coordinate_system: "synthetic_cartesian_metres",
  vehicles,
  traffic_lights: [{ traffic_light_id: "demo_01", phase_index: index % 2, phase_id: "phase", state }],
  ...(waiting === undefined ? {} : { metrics: {
    cumulative_waiting_time_s: waiting,
    active_vehicle_count: vehicles.length,
    arrived_vehicle_count: index,
    measurement: "sum_waiting_vehicle_intervals_x_step_duration",
  } }),
});

const text = [
  frame(0, [vehicle("a", 0)], "GrGr"),
  frame(1, [vehicle("a", 10), vehicle("b", 30)], "yryr"),
  frame(2, [vehicle("b", 40)], "rrrr"),
].join("\n");

const parse = () => parseReplayJsonl(text, {
  frameCount: 3,
  durationS: 2,
  coordinateSystem: "synthetic_cartesian_metres",
  trafficLightId: "demo_01",
});

const tests: Array<[string, () => void]> = [];
const test = (name: string, callback: () => void) => tests.push([name, callback]);

test("frame lookup interpolates only identities verified in adjacent frames", () => {
  const stream = parse();
  const middle = frameAtTime(stream, 0.5);
  assert.deepEqual(middle.vehicles.map((item) => item.vehicle_id), ["a"]);
  assert.equal(middle.vehicles[0].x_m, 5);
  assert.equal(Math.round(middle.vehicles[0].angle_deg), 360);
  assert.equal(middle.traffic_lights[0].state, "GrGr");
  assert.deepEqual(frameAtTime(stream, 1).vehicles.map((item) => item.vehicle_id), ["a", "b"]);
  assert.deepEqual(frameAtTime(stream, 1.5).vehicles.map((item) => item.vehicle_id), ["b"]);
});

test("seek and shared monotonic timing clamp to the complete Fixed replay", () => {
  assert.equal(advancePlayback(100, 2_000, 4, 532), 108);
  assert.equal(advancePlayback(531, 2_000, 1, 532), 532);
  assert.equal(frameAtTime(parse(), -20).simulation_time_s, 0);
  assert.equal(frameAtTime(parse(), 200).simulation_time_s, 2);
});

test("video freezes without looping while simulations can continue", () => {
  assert.equal(videoTimeAtReplayTime(300, 263.972), 263.972);
  assert.equal(sourceStatus(264, 263.972, "video"), "Video ended");
  assert.equal(sourceStatus(524, 523, "simulation"), "Simulation finished");
  assert.equal(sourceStatus(524, 532, "simulation"), "Playing");
});

test("actual SUMO TLS characters map to distinct signal lamp colors", () => {
  assert.equal(replaySignalColor("G"), "#70f8a7");
  assert.equal(replaySignalColor("g"), "#2ad083");
  assert.equal(replaySignalColor("y"), "#ffd15c");
  assert.equal(replaySignalColor("r"), "#ff5964");
  assert.equal(replaySignalColor("O"), "#667680");
});

test("switching video source preserves shared time and playback state", () => {
  const switched = switchVideoSource({ source: "original_video" as const, timeS: 150, playing: true }, "annotated_video", true);
  assert.deepEqual(switched, { source: "annotated_video", timeS: 150, playing: true });
  assert.throws(() => switchVideoSource(switched, "original_video", false), /unavailable/);
});

test("malformed, unordered and incompatible replay records fail loudly", () => {
  assert.throws(() => parseReplayJsonl("not json", { coordinateSystem: "synthetic_cartesian_metres", trafficLightId: "demo_01" }), /invalid JSON/);
  const unordered = [frame(0, []), JSON.stringify({ ...JSON.parse(frame(1, [])), simulation_time_s: 0 })].join("\n");
  assert.throws(() => parseReplayJsonl(unordered, { coordinateSystem: "synthetic_cartesian_metres", trafficLightId: "demo_01" }), /timestamps/);
  assert.throws(() => parseReplayJsonl(frame(0, []), { coordinateSystem: "wrong", trafficLightId: "demo_01" }), /coordinate system/);
});

test("recorded waiting totals follow seek, pause, restart and completion", () => {
  const stream = parseReplayJsonl([
    frame(0, [vehicle("a", 0)], "GrGr", 0),
    frame(1, [vehicle("a", 10)], "GrGr", 2),
    frame(2, [], "rrrr", 5),
  ].join("\n"), {
    frameCount: 3,
    durationS: 2,
    coordinateSystem: "synthetic_cartesian_metres",
    trafficLightId: "demo_01",
  });
  assert.equal(stream.waitingSeriesAvailable, true);
  assert.equal(replayMetricsAtTime(stream, 0)?.cumulative_waiting_time_s, 0);
  assert.equal(replayMetricsAtTime(stream, 1.8)?.cumulative_waiting_time_s, 2);
  assert.equal(replayMetricsAtTime(stream, 0.5)?.cumulative_waiting_time_s, 0);
  assert.equal(replayMetricsAtTime(stream, 2)?.cumulative_waiting_time_s, 5);
  assert.equal(replayMetricsAtTime(stream, 2)?.cumulative_waiting_time_s, replayMetricsAtTime(stream, 2)?.cumulative_waiting_time_s);
});

test("old replay remains compatible and incomplete or decreasing series fails", () => {
  const legacy = parse();
  assert.equal(legacy.waitingSeriesAvailable, false);
  assert.equal(replayMetricsAtTime(legacy, 1), null);
  const partial = [frame(0, [], "GrGr", 0), frame(1, [])].join("\n");
  assert.throws(() => parseReplayJsonl(partial, { coordinateSystem: "synthetic_cartesian_metres", trafficLightId: "demo_01" }), /incomplete/);
  const decreasing = [frame(0, [], "GrGr", 0), frame(1, [], "GrGr", 2), frame(2, [], "GrGr", 1)].join("\n");
  assert.throws(() => parseReplayJsonl(decreasing, { coordinateSystem: "synthetic_cartesian_metres", trafficLightId: "demo_01" }), /decreasing/);
});

const manifestFor = (
  selection: string,
  video: ReplayManifest["video"],
  originalAvailable: boolean,
) => ({
  schema_version: "1.0",
  dataset_id: `${selection}-bundle`,
  selection_id: selection,
  display_name: selection,
  video,
  network_geometry: { scenario_id: "single_intersection", coordinate_system: "synthetic_cartesian_metres" },
  assets: {
    original_video: { available: originalAvailable, url: originalAvailable ? "/o" : null },
    annotated_video: { available: true, url: "/a" },
    fixed_replay: { available: true, url: "/f" },
    gap_v1_replay: { available: true, url: "/g" },
  },
} as unknown as ReplayManifest);

const demo1Manifest = manifestFor("demo1", { duration_s: 263.972042, annotated_duration_s: 263.972306, camera_orientation_verified: false }, true);
const demo2Manifest = manifestFor("demo2", {
  duration_s: null,
  annotated_duration_s: 156.03,
  camera_orientation_verified: false,
  source_kind: "annotated_only",
  original_video_available: false,
}, false);

test("both allowlisted datasets are recognised and demo1 stays the default", () => {
  assert.equal(DEFAULT_REPLAY_DATASET_ID, "demo1");
  assert.equal(isReplayDatasetId("demo1"), true);
  assert.equal(isReplayDatasetId("demo2"), true);
  for (const unknown of ["demo3", "../waiting-v1", "", "DEMO1", null]) assert.equal(isReplayDatasetId(unknown), false);
  assert.equal(datasetManifestUrl("demo2"), "/api/operator/ai-traffic/datasets/demo2/manifest");
});

test("dataset list parsing keeps honest availability and rejects unknown IDs", () => {
  const parsed = parseDatasetList({ datasets: [
    { dataset_id: "demo1", label: "Demo 1", description: "d1", default: true, available: true, detail: null, video_sources: ["original_video", "annotated_video"] },
    { dataset_id: "demo2", label: "Demo 2", description: "d2", default: false, available: false, detail: "replay asset directory is unavailable", video_sources: [] },
  ] });
  assert.equal(parsed[0].default, true);
  assert.equal(parsed[1].available, false);
  assert.equal(parsed[1].detail, "replay asset directory is unavailable");
  assert.throws(() => parseDatasetList({ datasets: [{ dataset_id: "../etc", available: true, video_sources: [] }] }), /unknown or duplicate/);
  assert.throws(() => parseDatasetList({ datasets: [
    { dataset_id: "demo1", available: true, video_sources: [] },
    { dataset_id: "demo1", available: true, video_sources: [] },
  ] }), /unknown or duplicate/);
});

test("annotated-only dataset never offers or substitutes an original video", () => {
  assert.equal(isAnnotatedOnly(demo2Manifest), true);
  assert.deepEqual(availableVideoSources(demo2Manifest), ["annotated_video"]);
  assert.equal(defaultVideoSource(demo2Manifest), "annotated_video");
  assert.equal(videoDurationFor(demo2Manifest, "original_video"), undefined);
  assert.equal(videoDurationFor(demo2Manifest, "annotated_video"), 156.03);
  assert.throws(() => switchVideoSource({ source: "annotated_video" as const, timeS: 3, playing: false }, "original_video", demo2Manifest.assets.original_video.available), /unavailable/);
});

test("demo1 keeps original and annotated video switching", () => {
  assert.equal(isAnnotatedOnly(demo1Manifest), false);
  assert.deepEqual(availableVideoSources(demo1Manifest), ["original_video", "annotated_video"]);
  assert.equal(defaultVideoSource(demo1Manifest), "annotated_video");
  assert.equal(videoDurationFor(demo1Manifest, "original_video"), 263.972042);
});

test("a manifest served for another dataset is rejected", () => {
  assert.doesNotThrow(() => assertManifestSelection(demo2Manifest, "demo2"));
  assert.throws(() => assertManifestSelection(demo1Manifest, "demo2"), /belongs to demo1/);
  assert.throws(() => assertManifestSelection({ ...demo1Manifest, selection_id: undefined }, "demo1"), /unknown dataset/);
});

test("rapid dataset switching ignores every stale response", () => {
  const sequencer = createRequestSequencer();
  const demo1Request = sequencer.next();
  const demo2Request = sequencer.next();
  const demo1Again = sequencer.next();
  assert.equal(sequencer.isCurrent(demo1Request), false);
  assert.equal(sequencer.isCurrent(demo2Request), false);
  assert.equal(sequencer.isCurrent(demo1Again), true);
});

test("dataset switches restart paused at zero and durations come from each replay", () => {
  assert.deepEqual(initialPlayback(), { timeS: 0, playing: false });
  const short = parse();
  const longer = parseReplayJsonl([frame(0, []), frame(1, []), frame(2, []), frame(3, [])].join("\n"), {
    coordinateSystem: "synthetic_cartesian_metres",
    trafficLightId: "demo_01",
  });
  assert.equal(replayTimelineDuration(short, longer), 3);
  assert.equal(replayTimelineDuration(longer, short), 3);
  assert.equal(advancePlayback(initialPlayback().timeS, 10_000, 4, replayTimelineDuration(short, longer)), 3);
});

test("intersection names are display labels only; dataset IDs stay demo1/demo2", () => {
  assert.deepEqual([...REPLAY_DATASET_IDS], ["demo1", "demo2"]);
  assert.equal(REPLAY_DATASET_LABELS.demo1, "Center Street & 500 West Intersection");
  assert.equal(REPLAY_DATASET_LABELS.demo2, "Center Street & University Avenue Intersection");
  assert.equal(datasetManifestUrl("demo1"), "/api/operator/ai-traffic/datasets/demo1/manifest");
  for (const label of Object.values(REPLAY_DATASET_LABELS)) assert.doesNotMatch(label, /Original intersection|New intersection/);
});

let failures = 0;
for (const [name, callback] of tests) {
  try {
    callback();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`FAIL ${name}`);
    console.error(error);
  }
}
if (failures) process.exitCode = 1;
