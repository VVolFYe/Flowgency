import assert from "node:assert/strict";
import test from "node:test";
import { groupAlertsForPlayback, PlaybackGate } from "../lib/voice-alert-coordinator.ts";

test("matching simultaneous emergency events aggregate while FIFO order is retained", () => {
  const grouped = groupAlertsForPlayback([
    { event_id: "e1", message_id: "emergency.detected" },
    { event_id: "e2", message_id: "emergency.detected" },
    { event_id: "r1", message_id: "traffic.congestion_sustained" },
  ]);
  assert.deepEqual(grouped.map((group) => group.map((alert) => alert.event_id)), [["e1", "e2"], ["r1"]]);
});

test("playback gate never admits more than one active playback", () => {
  const gate = new PlaybackGate();
  assert.equal(gate.begin(), true);
  assert.equal(gate.begin(), false);
  assert.equal(gate.maxActiveObserved, 1);
  gate.end();
  assert.equal(gate.begin(), true);
  assert.equal(gate.maxActiveObserved, 1);
});
