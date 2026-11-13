"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type {
  Lane,
  NetworkGeometry,
  SimulationScenario,
  SimulationSnapshot,
  SimulationStatus,
  Vehicle,
} from "@/lib/contracts";

type ConnectionState = "connecting" | "connected" | "reconnecting" | "offline";
type VehicleFrame = Map<string, Vehicle>;

interface ViewState { zoom: number; panX: number; panY: number }
interface Size { width: number; height: number }
interface Transition {
  from: VehicleFrame;
  to: VehicleFrame;
  startedAt: number;
  durationMs: number;
  runId: string;
  scenarioId: string;
}

interface SignalLampGroup {
  trafficLightId: string;
  linkIndex: number;
  fromLane: string;
  toLanes: string[];
  movements: string[];
  stop: { x_m: number; y_m: number };
  previous: { x_m: number; y_m: number };
  offsetIndex: number;
  offsetCount: number;
}

type HoveredMarker =
  | { kind: "controller"; id: string; x: number; y: number; maxLeft: number }
  | {
      kind: "lamp";
      trafficLightId: string;
      linkIndex: number;
      fromLane: string;
      toLanes: string[];
      movements: string[];
      x: number;
      y: number;
      maxLeft: number;
    };

const vehicleMap = (vehicles: Vehicle[] | undefined): VehicleFrame =>
  new Map((vehicles ?? []).map((vehicle) => [vehicle.vehicle_id, vehicle]));

const interpolateAngle = (from: number, to: number, progress: number) => {
  const delta = ((to - from + 540) % 360) - 180;
  return from + delta * progress;
};

function interpolatedVehicles(transition: Transition, now: number): VehicleFrame {
  if (transition.durationMs <= 0) return transition.to;
  const progress = Math.min(1, Math.max(0, (now - transition.startedAt) / transition.durationMs));
  const result = new Map<string, Vehicle>();
  transition.to.forEach((target, id) => {
    const source = transition.from.get(id) ?? target;
    result.set(id, {
      ...target,
      x_m: source.x_m + (target.x_m - source.x_m) * progress,
      y_m: source.y_m + (target.y_m - source.y_m) * progress,
      angle_deg: interpolateAngle(source.angle_deg, target.angle_deg, progress),
    });
  });
  return result;
}

function configureCanvas(canvas: HTMLCanvasElement, size: Size) {
  const ratio = window.devicePixelRatio || 1;
  const targetWidth = Math.round(size.width * ratio);
  const targetHeight = Math.round(size.height * ratio);
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
  }
  const context = canvas.getContext("2d");
  context?.setTransform(ratio, 0, 0, ratio, 0, 0);
  return context;
}

function projection(geometry: NetworkGeometry, size: Size, view: ViewState) {
  const { bounds } = geometry;
  const worldWidth = Math.max(1, bounds.max_x_m - bounds.min_x_m);
  const worldHeight = Math.max(1, bounds.max_y_m - bounds.min_y_m);
  const padding = Math.max(24, Math.min(size.width, size.height) * 0.06);
  const baseScale = Math.max(
    0.0001,
    Math.min(
      Math.max(1, size.width - padding * 2) / worldWidth,
      Math.max(1, size.height - padding * 2) / worldHeight,
    ),
  );
  const scale = baseScale * view.zoom;
  const centerX = size.width / 2 + view.panX;
  const centerY = size.height / 2 + view.panY;
  const worldCenterX = (bounds.min_x_m + bounds.max_x_m) / 2;
  const worldCenterY = (bounds.min_y_m + bounds.max_y_m) / 2;
  return {
    baseScale,
    scale,
    screen: (point: { x_m: number; y_m: number }) => ({
      x: centerX + (point.x_m - worldCenterX) * scale,
      y: centerY - (point.y_m - worldCenterY) * scale,
    }),
  };
}

function drawPath(
  context: CanvasRenderingContext2D,
  shape: Array<{ x_m: number; y_m: number }>,
  screen: (point: { x_m: number; y_m: number }) => { x: number; y: number },
) {
  context.beginPath();
  shape.forEach((point, index) => {
    const position = screen(point);
    if (index === 0) context.moveTo(position.x, position.y);
    else context.lineTo(position.x, position.y);
  });
}

function signalColor(state: string | undefined) {
  if (state === "G" || state === "g") return "#61f69b";
  if (state === "y" || state === "Y") return "#f3bd4b";
  if (state === "r" || state === "R") return "#ff5964";
  return "#53616c";
}

function signalAppearance(state: string | undefined) {
  switch (state) {
    case "G": return { color: "#61f69b", outline: "#c9ffdc", glow: 9, label: "priority green" };
    case "g": return { color: "#28c77c", outline: "#82dfac", glow: 4, label: "permissive green" };
    case "s": return { color: "#43b98a", outline: "#9ad9bf", glow: 3, label: "stop-then-go green" };
    case "Y": return { color: "#ffd15c", outline: "#fff0b2", glow: 8, label: "priority yellow" };
    case "y": return { color: "#e9a936", outline: "#f6d28a", glow: 6, label: "permissive yellow" };
    case "r":
    case "R": return { color: "#ff5964", outline: "#ffb1b6", glow: 7, label: "red" };
    case "u": return { color: "#e9843d", outline: "#ffc291", glow: 6, label: "red and yellow" };
    case "o": return { color: "#a98235", outline: "#e2c278", glow: 2, label: "off, blinking" };
    case "O": return { color: "#26343c", outline: "#64747d", glow: 0, label: "off" };
    default: return { color: "#53616c", outline: "#8a9aa3", glow: 0, label: "state unavailable" };
  }
}

function signalLampPosition(
  group: SignalLampGroup,
  screen: (point: { x_m: number; y_m: number }) => { x: number; y: number },
) {
  const stop = screen(group.stop);
  const previous = screen(group.previous);
  const length = Math.max(0.001, Math.hypot(stop.x - previous.x, stop.y - previous.y));
  const ux = (stop.x - previous.x) / length;
  const uy = (stop.y - previous.y) / length;
  const spread = (group.offsetIndex - (group.offsetCount - 1) / 2) * 9;
  return {
    x: stop.x - ux * 8 - uy * spread,
    y: stop.y - uy * 8 + ux * spread,
  };
}

export function SimulationCanvas({
  geometry,
  scenario,
  snapshot,
  status,
  connection,
}: {
  geometry: NetworkGeometry;
  scenario: SimulationScenario | null;
  snapshot: SimulationSnapshot | null;
  status: SimulationStatus;
  connection: ConnectionState;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const staticCanvasRef = useRef<HTMLCanvasElement>(null);
  const dynamicCanvasRef = useRef<HTMLCanvasElement>(null);
  const sizeRef = useRef<Size>({ width: 0, height: 0 });
  const viewRef = useRef<ViewState>({ zoom: 1, panX: 0, panY: 0 });
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const transitionRef = useRef<Transition | null>(null);
  const previousSnapshotRef = useRef<SimulationSnapshot | null>(null);
  const lastSnapshotAtRef = useRef(0);
  const [viewRevision, setViewRevision] = useState(0);
  const [hoveredMarker, setHoveredMarker] = useState<HoveredMarker | null>(null);

  const lanes = useMemo(
    () => geometry.edges.flatMap((edge) => edge.lanes.map((lane) => ({ lane, internal: edge.is_internal }))),
    [geometry],
  );
  const laneById = useMemo(() => {
    const result = new Map<string, Lane>();
    lanes.forEach(({ lane }) => result.set(lane.lane_id, lane));
    return result;
  }, [lanes]);
  const junctionById = useMemo(
    () => new Map(geometry.junctions.map((junction) => [junction.junction_id, junction])),
    [geometry],
  );
  const controllerPoints = useMemo(
    () => geometry.traffic_lights.flatMap((light) =>
      (light.junctions ?? []).map((junction) => ({
        id: light.traffic_light_id,
        x_m: junction.x_m,
        y_m: junction.y_m,
      })),
    ),
    [geometry],
  );
  const targetPoints = useMemo(() => scenario?.target_mappings.flatMap((target) =>
    target.candidates.flatMap((candidate) => {
      const junction = junctionById.get(candidate.junction_id);
      return junction ? [{ ...junction, label: target.intersection_id, status: target.mapping_status }] : [];
    }),
  ) ?? [], [junctionById, scenario]);
  const signalLampGroups = useMemo(() => {
    if (geometry.scenario_selection_id === "single_intersection") return [];
    const groupedLinks = new Map<string, typeof geometry.controlled_links>();
    geometry.controlled_links.forEach((link) => {
      if (!link.traffic_light_id) return;
      const key = `${link.traffic_light_id}\u0000${link.from_lane}\u0000${link.link_index}`;
      groupedLinks.set(key, [...(groupedLinks.get(key) ?? []), link]);
    });
    const byIncomingLane = new Map<string, Array<Omit<SignalLampGroup, "offsetIndex" | "offsetCount">>>();
    groupedLinks.forEach((links) => {
      const first = links[0];
      const lane = laneById.get(first.from_lane);
      if (!lane || lane.shape.length < 2 || !first.traffic_light_id) return;
      const laneKey = `${first.traffic_light_id}\u0000${first.from_lane}`;
      const group = {
        trafficLightId: first.traffic_light_id,
        linkIndex: first.link_index,
        fromLane: first.from_lane,
        toLanes: Array.from(new Set(links.map((link) => link.to_lane))),
        movements: Array.from(new Set(links.map((link) => link.movement))),
        stop: lane.shape[lane.shape.length - 1],
        previous: lane.shape[lane.shape.length - 2],
      };
      byIncomingLane.set(laneKey, [...(byIncomingLane.get(laneKey) ?? []), group]);
    });
    return Array.from(byIncomingLane.values()).flatMap((groups) => {
      const sorted = groups.sort((a, b) => a.linkIndex - b.linkIndex);
      return sorted.map((group, offsetIndex) => ({
        ...group,
        offsetIndex,
        offsetCount: sorted.length,
      }));
    });
  }, [geometry, laneById]);

  const resetView = useCallback(() => {
    viewRef.current = { zoom: 1, panX: 0, panY: 0 };
    setHoveredMarker(null);
    setViewRevision((value) => value + 1);
  }, []);

  useEffect(() => {
    const next = snapshot;
    if (!next) {
      transitionRef.current = null;
      previousSnapshotRef.current = null;
      lastSnapshotAtRef.current = 0;
      return;
    }
    const now = performance.now();
    const previous = previousSnapshotRef.current;
    const scenarioId = next.scenario_selection_id ?? next.scenario_id;
    const previousScenarioId = previous?.scenario_selection_id ?? previous?.scenario_id;
    const sameRun = previous?.run_id === next.run_id && previousScenarioId === scenarioId;
    const nextVehicles = vehicleMap(next.vehicles);
    let from = nextVehicles;
    let durationMs = 0;
    if (sameRun && status.state === "running") {
      const active = transitionRef.current;
      from = active ? interpolatedVehicles(active, now) : vehicleMap(previous?.vehicles);
      const elapsed = lastSnapshotAtRef.current ? now - lastSnapshotAtRef.current : 250;
      durationMs = status.simulation_speed >= 16
        ? Math.min(180, Math.max(60, elapsed * 0.55))
        : Math.min(550, Math.max(120, elapsed));
      let largestMove = 0;
      nextVehicles.forEach((vehicle, id) => {
        const source = from.get(id);
        if (source) largestMove = Math.max(largestMove, Math.hypot(vehicle.x_m - source.x_m, vehicle.y_m - source.y_m));
      });
      const diagonal = Math.hypot(
        geometry.bounds.max_x_m - geometry.bounds.min_x_m,
        geometry.bounds.max_y_m - geometry.bounds.min_y_m,
      );
      if (largestMove > Math.max(120, diagonal * 0.08)) durationMs = Math.min(durationMs, 80);
    }
    transitionRef.current = { from, to: nextVehicles, startedAt: now, durationMs, runId: next.run_id, scenarioId };
    previousSnapshotRef.current = next;
    lastSnapshotAtRef.current = now;
  }, [geometry.bounds, snapshot, status.simulation_speed, status.state]);

  useEffect(() => {
    if (status.state === "running" || !transitionRef.current) return;
    const now = performance.now();
    const current = interpolatedVehicles(transitionRef.current, now);
    transitionRef.current = { ...transitionRef.current, from: current, to: current, startedAt: now, durationMs: 0 };
  }, [status.state]);

  const drawStatic = useCallback(() => {
    const canvas = staticCanvasRef.current;
    const size = sizeRef.current;
    if (!canvas || size.width <= 0 || size.height <= 0) return;
    const context = configureCanvas(canvas, size);
    if (!context) return;
    context.clearRect(0, 0, size.width, size.height);
    context.fillStyle = "#0b1115";
    context.fillRect(0, 0, size.width, size.height);
    const { screen, scale } = projection(geometry, size, viewRef.current);

    geometry.junctions.forEach((junction) => {
      if (junction.shape.length < 3) return;
      drawPath(context, junction.shape, screen);
      context.closePath();
      context.fillStyle = junction.type === "traffic_light" ? "#202c34" : "#151e24";
      context.fill();
    });

    lanes.forEach(({ lane, internal }) => {
      if (lane.shape.length < 2) return;
      drawPath(context, lane.shape, screen);
      context.lineWidth = Math.min(12, Math.max(internal ? 0.45 : 0.7, lane.width_m * scale));
      context.lineCap = "round";
      context.lineJoin = "round";
      context.strokeStyle = internal ? "#39464d" : "#2b3941";
      context.stroke();
      if (viewRef.current.zoom >= 2.2) {
        context.lineWidth = Math.max(0.45, Math.min(1, scale * 0.2));
        context.setLineDash(internal ? [3, 4] : [7, 8]);
        context.strokeStyle = internal ? "rgba(205,220,226,.2)" : "rgba(205,220,226,.3)";
        context.stroke();
        context.setLineDash([]);
      }
    });

    if (geometry.scenario_selection_id !== "single_intersection") {
      controllerPoints.forEach((point) => {
        const position = screen(point);
        context.beginPath();
        context.arc(position.x, position.y, 3.5, 0, Math.PI * 2);
        context.fillStyle = "#7b8b95";
        context.fill();
        context.lineWidth = 1.5;
        context.strokeStyle = "#d1dce2";
        context.stroke();
      });
    }

    targetPoints.forEach((point) => {
      const position = screen(point);
      context.save();
      context.translate(position.x, position.y);
      context.rotate(Math.PI / 4);
      context.fillStyle = "#f0bc55";
      context.fillRect(-4, -4, 8, 8);
      context.restore();
      context.fillStyle = "#f5d58f";
      context.font = "600 10px ui-monospace, monospace";
      context.fillText(point.label, position.x + 7, position.y - 6);
    });
  }, [controllerPoints, geometry, lanes, targetPoints]);

  const drawSyntheticSignals = useCallback((context: CanvasRenderingContext2D) => {
    if (geometry.scenario_selection_id !== "single_intersection") return;
    const size = sizeRef.current;
    const { screen } = projection(geometry, size, viewRef.current);
    const junction = geometry.junctions.find((item) => item.type === "traffic_light");
    const center = junction ?? {
      x_m: (geometry.bounds.min_x_m + geometry.bounds.max_x_m) / 2,
      y_m: (geometry.bounds.min_y_m + geometry.bounds.max_y_m) / 2,
    };
    const grouped = new Map<string, typeof geometry.controlled_links>();
    geometry.controlled_links.forEach((link) => grouped.set(link.from_lane, [...(grouped.get(link.from_lane) ?? []), link]));
    grouped.forEach((links, laneId) => {
      const lane = laneById.get(laneId);
      if (!lane || lane.shape.length < 2) return;
      const sorted = [...lane.shape].sort((a, b) =>
        Math.hypot(a.x_m - center.x_m, a.y_m - center.y_m) - Math.hypot(b.x_m - center.x_m, b.y_m - center.y_m));
      const near = sorted[0];
      const next = sorted[1];
      const length = Math.max(0.001, Math.hypot(next.x_m - near.x_m, next.y_m - near.y_m));
      const ux = (next.x_m - near.x_m) / length;
      const uy = (next.y_m - near.y_m) / length;
      links.sort((a, b) => a.link_index - b.link_index).forEach((link, index) => {
        const spread = (index - (links.length - 1) / 2) * 3.3;
        const position = screen({ x_m: near.x_m + ux * 5 - uy * spread, y_m: near.y_m + uy * 5 + ux * spread });
        const color = signalColor(snapshot?.traffic_light_state?.[link.link_index]);
        context.beginPath(); context.arc(position.x, position.y, 7, 0, Math.PI * 2);
        context.fillStyle = "#071014"; context.fill();
        context.lineWidth = 2; context.strokeStyle = "#65737c"; context.stroke();
        context.beginPath(); context.arc(position.x, position.y, 4, 0, Math.PI * 2);
        context.fillStyle = color; context.shadowColor = color; context.shadowBlur = 9; context.fill(); context.shadowBlur = 0;
      });
    });
  }, [geometry, laneById, snapshot?.traffic_light_state]);

  const drawLondonSignals = useCallback((context: CanvasRenderingContext2D) => {
    if (geometry.scenario_selection_id === "single_intersection") return;
    const { screen } = projection(geometry, sizeRef.current, viewRef.current);
    const radius = Math.min(6, Math.max(3.25, 3.25 + Math.log2(Math.max(1, viewRef.current.zoom)) * 0.7));
    signalLampGroups.forEach((group) => {
      const controller = snapshot?.traffic_light_controllers?.[group.trafficLightId];
      const state = controller?.traffic_light_state[group.linkIndex];
      const appearance = signalAppearance(state);
      const position = signalLampPosition(group, screen);
      context.beginPath();
      context.arc(position.x, position.y, radius + 2.25, 0, Math.PI * 2);
      context.fillStyle = "rgba(4, 10, 13, .94)";
      context.fill();
      context.lineWidth = state ? 1.35 : 1;
      context.strokeStyle = state ? appearance.outline : "#687983";
      context.stroke();
      context.beginPath();
      context.arc(position.x, position.y, radius, 0, Math.PI * 2);
      context.fillStyle = appearance.color;
      context.shadowColor = appearance.color;
      context.shadowBlur = appearance.glow;
      context.fill();
      context.shadowBlur = 0;
      if (state === "g" || state === "y" || state === "s" || state === "o") {
        context.beginPath();
        context.arc(position.x, position.y, Math.max(1, radius - 2), 0, Math.PI * 2);
        context.strokeStyle = "rgba(4, 10, 13, .58)";
        context.lineWidth = 1;
        context.stroke();
      }
    });
  }, [geometry, signalLampGroups, snapshot?.traffic_light_controllers]);

  const drawDynamic = useCallback((now: number) => {
    const canvas = dynamicCanvasRef.current;
    const size = sizeRef.current;
    if (!canvas || size.width <= 0 || size.height <= 0) return;
    const context = configureCanvas(canvas, size);
    if (!context) return;
    context.clearRect(0, 0, size.width, size.height);
    drawSyntheticSignals(context);
    drawLondonSignals(context);
    const { screen, scale } = projection(geometry, size, viewRef.current);
    const vehicles = transitionRef.current
      ? interpolatedVehicles(transitionRef.current, now)
      : vehicleMap(snapshot?.vehicles);
    vehicles.forEach((vehicle) => {
      const position = screen(vehicle);
      const length = Math.min(15, Math.max(3.5, 4.6 * scale));
      const width = Math.min(8, Math.max(2.2, 1.9 * scale));
      context.save();
      context.translate(position.x, position.y);
      context.rotate((vehicle.angle_deg * Math.PI) / 180);
      context.beginPath();
      context.roundRect(-width / 2, -length / 2, width, length, Math.min(2.5, width / 2));
      context.fillStyle = vehicle.vehicle_type.toLowerCase().includes("bus") ? "#f3bd4b" : "#dce9ef";
      context.shadowColor = "rgba(115,226,255,.5)";
      context.shadowBlur = viewRef.current.zoom >= 2 ? 5 : 2;
      context.fill();
      context.restore();
    });
  }, [drawLondonSignals, drawSyntheticSignals, geometry, snapshot?.vehicles]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const resize = new ResizeObserver(([entry]) => {
      sizeRef.current = { width: entry.contentRect.width, height: entry.contentRect.height };
      drawStatic();
      drawDynamic(performance.now());
    });
    resize.observe(host);
    return () => resize.disconnect();
  }, [drawDynamic, drawStatic]);

  useEffect(() => {
    drawStatic();
    drawDynamic(performance.now());
  }, [drawDynamic, drawStatic, viewRevision]);

  useEffect(() => {
    let frame = 0;
    const animate = (now: number) => {
      drawDynamic(now);
      if (status.state === "running" && connection === "connected") frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [connection, drawDynamic, status.state]);

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const pointerX = event.clientX - rect.left;
    const pointerY = event.clientY - rect.top;
    const view = viewRef.current;
    const current = projection(geometry, sizeRef.current, view);
    const nextZoom = Math.min(40, Math.max(0.7, view.zoom * Math.exp(-event.deltaY * 0.0015)));
    const worldDx = (pointerX - sizeRef.current.width / 2 - view.panX) / current.scale;
    const worldDy = -(pointerY - sizeRef.current.height / 2 - view.panY) / current.scale;
    const nextScale = current.baseScale * nextZoom;
    viewRef.current = {
      zoom: nextZoom,
      panX: pointerX - sizeRef.current.width / 2 - worldDx * nextScale,
      panY: pointerY - sizeRef.current.height / 2 + worldDy * nextScale,
    };
    setViewRevision((value) => value + 1);
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY, panX: viewRef.current.panX, panY: viewRef.current.panY };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (drag) {
      viewRef.current = {
        ...viewRef.current,
        panX: drag.panX + event.clientX - drag.x,
        panY: drag.panY + event.clientY - drag.y,
      };
      setHoveredMarker(null);
      setViewRevision((value) => value + 1);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const pointer = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const { screen } = projection(geometry, sizeRef.current, viewRef.current);
    let closestLamp: { group: SignalLampGroup; x: number; y: number; distance: number } | null = null;
    for (const group of signalLampGroups) {
      const position = signalLampPosition(group, screen);
      const distance = Math.hypot(position.x - pointer.x, position.y - pointer.y);
      if (distance <= 12 && (!closestLamp || distance < closestLamp.distance)) {
        closestLamp = { group, ...position, distance };
      }
    }
    if (closestLamp) {
      setHoveredMarker({
        kind: "lamp",
        trafficLightId: closestLamp.group.trafficLightId,
        linkIndex: closestLamp.group.linkIndex,
        fromLane: closestLamp.group.fromLane,
        toLanes: closestLamp.group.toLanes,
        movements: closestLamp.group.movements,
        x: closestLamp.x,
        y: closestLamp.y,
        maxLeft: sizeRef.current.width - 305,
      });
      return;
    }
    let closest: { id: string; x: number; y: number; distance: number } | null = null;
    for (const point of controllerPoints) {
      const position = screen(point);
      const distance = Math.hypot(position.x - pointer.x, position.y - pointer.y);
      if (distance <= 12 && (!closest || distance < closest.distance)) closest = { id: point.id, ...position, distance };
    }
    if (closest) {
      const match: { id: string; x: number; y: number; distance: number } = closest;
      setHoveredMarker({ kind: "controller", id: match.id, x: match.x, y: match.y, maxLeft: sizeRef.current.width - 285 });
    } else {
      setHoveredMarker(null);
    }
  };

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
  };

  const hoveredController = hoveredMarker?.kind === "controller"
    ? snapshot?.traffic_light_controllers?.[hoveredMarker.id]
    : null;
  const hoveredLampController = hoveredMarker?.kind === "lamp"
    ? snapshot?.traffic_light_controllers?.[hoveredMarker.trafficLightId]
    : null;
  const hoveredLampState = hoveredMarker?.kind === "lamp"
    ? hoveredLampController?.traffic_light_state[hoveredMarker.linkIndex]
    : undefined;

  return (
    <div
      ref={hostRef}
      className="relative h-full min-h-[390px] touch-none overflow-hidden rounded-[20px] bg-[#0b1115]"
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onPointerLeave={() => { if (!dragRef.current) setHoveredMarker(null); }}
    >
      <canvas ref={staticCanvasRef} className="pointer-events-none absolute inset-0 block h-full w-full" aria-hidden="true" />
      <canvas ref={dynamicCanvasRef} className="pointer-events-none absolute inset-0 block h-full w-full" aria-label="Live SUMO road network and vehicles" />
      <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-white/10 bg-[#0b1115]/85 px-3 py-2 backdrop-blur">
        <div className="font-mono text-[10px] uppercase tracking-[.18em] text-[#7f909b]">SUMO Cartesian</div>
        <div className="mt-1 max-w-[260px] truncate text-xs text-[#b8c5cc]">{scenario?.display_name ?? geometry.scenario_selection_id}</div>
      </div>
      <button
        type="button"
        onClick={resetView}
        className="absolute right-4 top-4 rounded-lg border border-white/10 bg-[#111a20]/90 px-3 py-2 text-xs text-[#c5d1d7] transition hover:border-white/20 hover:bg-[#18232a]"
      >
        Fit network
      </button>
      {hoveredMarker && (
        <div
          className="pointer-events-none absolute z-10 max-w-[290px] rounded-lg border border-white/10 bg-[#071014]/95 px-3 py-2 text-[11px] shadow-xl"
          style={{ left: Math.max(8, Math.min(hoveredMarker.x + 12, hoveredMarker.maxLeft)), top: Math.max(8, hoveredMarker.y - 42) }}
        >
          {hoveredMarker.kind === "lamp" ? (
            <>
              <div className="truncate font-mono text-[#d8e3e8]">{hoveredMarker.trafficLightId}</div>
              <div className="mt-1 text-[#aebcc4]">
                Link {hoveredMarker.linkIndex} · {signalAppearance(hoveredLampState).label} ({hoveredLampState ?? "?"})
              </div>
              <div className="mt-1 break-all font-mono text-[10px] text-[#71838d]">
                {hoveredMarker.fromLane} → {hoveredMarker.toLanes.join(", ")}
              </div>
              <div className="mt-1 text-[10px] text-[#71838d]">{hoveredMarker.movements.join(", ")}</div>
            </>
          ) : (
            <>
              <div className="truncate font-mono text-[#d8e3e8]">{hoveredMarker.id}</div>
              <div className="mt-1 text-[#83949e]">
                {hoveredController
                  ? `Phase ${hoveredController.current_phase_index} · ${hoveredController.remaining_phase_duration_s.toFixed(1)}s · state ${hoveredController.traffic_light_state}`
                  : "Controller state unavailable until the simulation starts"}
              </div>
            </>
          )}
        </div>
      )}
      {!snapshot && status.state !== "idle" && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center bg-[#0b1115]/60 text-sm text-[#9cabb4]">
          Waiting for first SUMO snapshot…
        </div>
      )}
    </div>
  );
}
