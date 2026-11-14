import assert from "node:assert/strict";
import {
  advancePlayback,
  frameAtTime,
  parseReplayJsonl,
  replaySignalColor,
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

const frame = (index: number, vehicles: ReturnType<typeof vehicle>[], state = "GrGr") => JSON.stringify({
  schema_version: "1.0",
  record_type: "frame",
  frame_index: index,
  simulation_time_s: index,
  coordinate_system: "synthetic_cartesian_metres",
  vehicles,
  traffic_lights: [{ traffic_light_id: "demo_01", phase_index: index % 2, phase_id: "phase", state }],
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
