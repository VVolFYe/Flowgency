import proj4 from "proj4";
import type { Feature, FeatureCollection } from "geojson";
import type { NetworkGeometry, SimulationSnapshot } from "./contracts";

export function mapCoordinates(geometry: NetworkGeometry) {
  if (geometry.coordinate_system === "synthetic_cartesian_metres") {
    // Local engineering scene, centered at zero, with no geographic basemap.
    const centerX = (geometry.bounds.min_x_m + geometry.bounds.max_x_m) / 2;
    const centerY = (geometry.bounds.min_y_m + geometry.bounds.max_y_m) / 2;
    return (x: number, y: number): [number, number] => [
      (x - centerX) / 6378137 * 180 / Math.PI,
      (2 * Math.atan(Math.exp((y - centerY) / 6378137)) - Math.PI / 2) * 180 / Math.PI,
    ];
  }
  const projection = geometry.projection;
  const offset = projection?.net_offset?.split(",").map(Number);
  if (!projection?.proj_parameter?.includes("+proj=") || !offset || offset.length !== 2 || !offset.every(Number.isFinite)) {
    throw new Error("Geographic projection is unavailable. Use the technical view.");
  }
  const transform = proj4(projection.proj_parameter, "EPSG:4326");
  return (x: number, y: number): [number, number] => {
    const result = transform.forward([x - offset[0], y - offset[1]]);
    if (!result.every(Number.isFinite)) throw new Error("Invalid geographic coordinates.");
    return [result[0], result[1]];
  };
}

export function roadFeatures(geometry: NetworkGeometry): FeatureCollection {
  const coordinates = mapCoordinates(geometry);
  const features: Feature[] = [];
  for (const edge of geometry.edges) {
    for (const lane of edge.lanes) {
      if (lane.shape.length < 2) continue;
      features.push({
        type: "Feature", properties: { width: lane.width_m, internal: edge.is_internal },
        geometry: { type: "LineString", coordinates: lane.shape.map(p => coordinates(p.x_m, p.y_m)) },
      });
    }
  }
  return { type: "FeatureCollection", features };
}

export function signalFeatures(geometry: NetworkGeometry, snapshot: SimulationSnapshot | null): FeatureCollection {
  const coordinates = mapCoordinates(geometry);
  const lanes = new Map(geometry.edges.flatMap(e => e.lanes.map(l => [l.lane_id, l] as const)));
  const seen = new Set<string>();
  const features: Feature[] = [];
  for (const link of geometry.controlled_links) {
    const tls = link.traffic_light_id ?? (geometry.traffic_lights.length === 1 ? geometry.traffic_lights[0].traffic_light_id : undefined);
    const lane = lanes.get(link.from_lane);
    const point = lane?.shape.at(-1);
    const key = `${tls}:${link.from_lane}:${link.link_index}`;
    if (!tls || !point || seen.has(key)) continue;
    seen.add(key);
    const state = snapshot?.traffic_light_controllers?.[tls]?.traffic_light_state ??
      (snapshot?.traffic_light_id === tls ? snapshot.traffic_light_state : null);
    const signal = state?.[link.link_index];
    const color = signal && "Ggs".includes(signal) ? "#43e890" :
      signal && "yYu".includes(signal) ? "#ffd24c" :
      signal && "rR".includes(signal) ? "#ff5362" : "#839293";
    features.push({ type: "Feature", properties: {
      color, tls, link: link.link_index, state: signal ?? "unavailable",
    }, geometry: { type: "Point", coordinates: coordinates(point.x_m, point.y_m) } });
  }
  return { type: "FeatureCollection", features };
}

export function demonstrationBuildings(geometry: NetworkGeometry): FeatureCollection {
  const coordinates = mapCoordinates(geometry);
  const b = geometry.bounds;
  const cx = (b.min_x_m + b.max_x_m) / 2, cy = (b.min_y_m + b.max_y_m) / 2;
  const dx = (b.max_x_m - b.min_x_m), dy = (b.max_y_m - b.min_y_m);
  const features: Feature[] = [];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    for (let index = 0; index < 3; index++) {
      const x = cx + sx * dx * (.1 + index * .11), y = cy + sy * dy * .18;
      const w = dx * .065, h = dy * .15;
      features.push({ type: "Feature", properties: { height: 7 + index * 3 },
        geometry: { type: "Polygon", coordinates: [[
          coordinates(x, y), coordinates(x + sx * w, y),
          coordinates(x + sx * w, y + sy * h), coordinates(x, y + sy * h), coordinates(x, y),
        ]] } });
    }
  }
  return { type: "FeatureCollection", features };
}
