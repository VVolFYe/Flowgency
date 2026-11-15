import assert from "node:assert/strict";
import test from "node:test";
import type { NetworkGeometry, SimulationSnapshot } from "../lib/contracts.ts";
import { mapCoordinates, signalFeatures } from "../lib/map-geometry.ts";

function geometry(): NetworkGeometry {
  return {
    schema_version: "1.0", scenario_id: "fixture", scenario_selection_id: "single_intersection",
    coordinate_system: "synthetic_cartesian_metres",
    bounds: { min_x_m: 0, min_y_m: 0, max_x_m: 300, max_y_m: 300 },
    edges: [{
      edge_id: "approach", from_junction_id: "in", to_junction_id: "center", function: "",
      is_internal: false, lanes: [{
        lane_id: "incoming", index: 0, speed_limit_mps: 13.9, length_m: 150, width_m: 3.2,
        shape: [{ x_m: 0, y_m: 150 }, { x_m: 140, y_m: 150 }],
      }],
    }],
    junctions: [], traffic_lights: [{ traffic_light_id: "tls-a" }, { traffic_light_id: "tls-b" }],
    controlled_links: ["tls-a", "tls-b"].map(traffic_light_id => ({
      traffic_light_id, link_index: 0, approach: "in", from_lane: "incoming", to_lane: "outgoing", movement: "straight",
    })),
  };
}

test("synthetic scene preserves centre and north without assigning London coordinates", () => {
  const project = mapCoordinates(geometry());
  assert.deepEqual(project(150, 150), [0, 0]);
  assert.ok(project(150, 151)[1] > project(150, 150)[1]);
});

test("London projection subtracts the supplied SUMO offset before inverse UTM conversion", () => {
  const london = { ...geometry(), coordinate_system: "sumo_cartesian_metres", projection: {
    proj_parameter: "+proj=utm +zone=30 +ellps=WGS84 +datum=WGS84 +units=m +no_defs",
    net_offset: "-699726.94,-5706063.16", original_boundary: null,
  } };
  const [longitude, latitude] = mapCoordinates(london)(2071.74 / 2, 2018.15 / 2);
  assert.ok(Math.abs(longitude - (-0.10874119106465768)) < 0.000001);
  assert.ok(Math.abs(latitude - 51.47912529679072) < 0.000001);
});

test("missing or malformed geographic metadata fails explicitly for technical fallback", () => {
  assert.throws(() => mapCoordinates({ ...geometry(), coordinate_system: "sumo_cartesian_metres" }), /projection/);
  assert.throws(() => mapCoordinates({ ...geometry(), coordinate_system: "sumo_cartesian_metres", projection: {
    proj_parameter: "+proj=utm +zone=30", net_offset: "unknown,0", original_boundary: null,
  } }), /projection/);
});

test("signals use their own controller state; unknown states stay unavailable", () => {
  const snapshot = { traffic_light_controllers: { "tls-a": { traffic_light_state: "G" } } } as unknown as SimulationSnapshot;
  const features = signalFeatures(geometry(), snapshot).features;
  assert.equal(features[0].properties?.state, "G");
  assert.equal(features[1].properties?.state, "unavailable");
  assert.notEqual(features[0].properties?.color, features[1].properties?.color);
});

test("only supported active emergency events mark their own intersection", () => {
  const snapshot = { emergency_events: [
    { intersection_id: "tls-a", priority_supported: true, state: "priority_active" },
    { intersection_id: "tls-b", priority_supported: true, state: "served" },
    { intersection_id: "tls-b", priority_supported: false, state: "priority_active" },
  ] } as unknown as SimulationSnapshot;
  const features = signalFeatures(geometry(), snapshot).features;
  assert.equal(features[0].properties?.priority, true);
  assert.equal(features[1].properties?.priority, false);
});

test("an unmapped signal is not assigned to an arbitrary intersection", () => {
  const network = geometry();
  delete network.controlled_links[0].traffic_light_id;
  assert.equal(signalFeatures(network, null).features.length, 1);
});
