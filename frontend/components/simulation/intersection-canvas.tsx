"use client";

import { useCallback, useEffect, useRef } from "react";
import type { Lane, NetworkGeometry, SimulationSnapshot, SimulationStatus } from "@/lib/contracts";
import {
  interpolatedVehicles,
  vehicleMap,
  type ConnectionState,
  type Transition,
} from "./simulation-provider";

function signalColor(state: string | undefined) {
  if (state === "G" || state === "g") return "#61f69b";
  if (state === "y" || state === "Y") return "#f3bd4b";
  if (state === "r" || state === "R") return "#ff5964";
  return "#53616c";
}

function drawRoundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
}

export function IntersectionCanvas({
  geometry,
  snapshot,
  status,
  connection,
  transitionRef,
}: {
  geometry: NetworkGeometry;
  snapshot: SimulationSnapshot | null;
  status: SimulationStatus;
  connection: ConnectionState;
  transitionRef: React.MutableRefObject<Transition | null>;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const sizeRef = useRef({ width: 0, height: 0 });

  const draw = useCallback((now: number) => {
    const canvas = canvasRef.current;
    const { width, height } = sizeRef.current;
    if (!canvas || width <= 0 || height <= 0) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const pixelRatio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * pixelRatio) || canvas.height !== Math.round(height * pixelRatio)) {
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
    }
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const padding = Math.max(28, Math.min(width, height) * 0.075);
    const bounds = geometry.bounds;
    const worldWidth = Math.max(1, bounds.max_x_m - bounds.min_x_m);
    const worldHeight = Math.max(1, bounds.max_y_m - bounds.min_y_m);
    const scale = Math.min((width - padding * 2) / worldWidth, (height - padding * 2) / worldHeight);
    const offsetX = (width - worldWidth * scale) / 2;
    const offsetY = (height - worldHeight * scale) / 2;
    const screen = (point: { x_m: number; y_m: number }) => ({
      x: offsetX + (point.x_m - bounds.min_x_m) * scale,
      y: height - offsetY - (point.y_m - bounds.min_y_m) * scale,
    });

    const grid = Math.max(25, worldWidth / 12);
    context.strokeStyle = "rgba(121, 152, 169, .055)";
    context.lineWidth = 1;
    for (let x = Math.ceil(bounds.min_x_m / grid) * grid; x <= bounds.max_x_m; x += grid) {
      const start = screen({ x_m: x, y_m: bounds.min_y_m });
      const end = screen({ x_m: x, y_m: bounds.max_y_m });
      context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke();
    }
    for (let y = Math.ceil(bounds.min_y_m / grid) * grid; y <= bounds.max_y_m; y += grid) {
      const start = screen({ x_m: bounds.min_x_m, y_m: y });
      const end = screen({ x_m: bounds.max_x_m, y_m: y });
      context.beginPath(); context.moveTo(start.x, start.y); context.lineTo(end.x, end.y); context.stroke();
    }

    geometry.junctions.forEach((junction) => {
      if (junction.shape.length < 3) return;
      context.beginPath();
      junction.shape.forEach((point, index) => {
        const position = screen(point);
        if (index === 0) context.moveTo(position.x, position.y);
        else context.lineTo(position.x, position.y);
      });
      context.closePath();
      context.fillStyle = junction.type === "traffic_light" ? "#202c34" : "#161f25";
      context.fill();
      context.strokeStyle = "#34434d";
      context.stroke();
    });

    const lanes = geometry.edges.flatMap((edge) => edge.lanes.map((lane) => ({ lane, internal: edge.is_internal })));
    lanes.forEach(({ lane, internal }) => {
      if (lane.shape.length < 2) return;
      context.beginPath();
      lane.shape.forEach((point, index) => {
        const position = screen(point);
        if (index === 0) context.moveTo(position.x, position.y);
        else context.lineTo(position.x, position.y);
      });
      context.lineWidth = Math.max(3, lane.width_m * scale);
      context.lineCap = "round";
      context.lineJoin = "round";
      context.strokeStyle = internal ? "#35434b" : "#2c3941";
      context.stroke();
      context.lineWidth = 1;
      context.setLineDash(internal ? [3, 4] : [7, 8]);
      context.strokeStyle = internal ? "rgba(186, 207, 216, .22)" : "rgba(186, 207, 216, .32)";
      context.stroke();
      context.setLineDash([]);
    });

    const laneById = new Map<string, Lane>();
    geometry.edges.forEach((edge) => edge.lanes.forEach((lane) => laneById.set(lane.lane_id, lane)));
    const junction = geometry.junctions.find((item) => item.type === "traffic_light");
    const center = junction ? { x_m: junction.x_m, y_m: junction.y_m } : {
      x_m: (bounds.min_x_m + bounds.max_x_m) / 2,
      y_m: (bounds.min_y_m + bounds.max_y_m) / 2,
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

    const transition = transitionRef.current;
    const vehicles = transition ? interpolatedVehicles(transition, now) : vehicleMap(snapshot?.vehicles);
    vehicles.forEach((vehicle) => {
      const position = screen(vehicle);
      const length = Math.max(7, 4.6 * scale);
      const vehicleWidth = Math.max(4, 1.9 * scale);
      context.save();
      context.translate(position.x, position.y);
      context.rotate((vehicle.angle_deg * Math.PI) / 180);
      drawRoundedRect(context, -vehicleWidth / 2, -length / 2, vehicleWidth, length, Math.min(2.5, vehicleWidth / 2));
      context.fillStyle = vehicle.vehicle_type.toLowerCase().includes("bus") ? "#f3bd4b" : "#dce9ef";
      context.shadowColor = "rgba(115, 226, 255, .55)"; context.shadowBlur = 5; context.fill();
      context.shadowBlur = 0;
      context.fillStyle = "#1c657c";
      context.fillRect(-vehicleWidth * .32, -length * .24, vehicleWidth * .64, length * .19);
      context.restore();
    });
  }, [geometry, snapshot, transitionRef]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const resize = new ResizeObserver(([entry]) => {
      sizeRef.current = { width: entry.contentRect.width, height: entry.contentRect.height };
      draw(performance.now());
    });
    resize.observe(host);
    return () => resize.disconnect();
  }, [draw]);

  useEffect(() => {
    let frame = 0;
    const animate = (now: number) => {
      draw(now);
      const transition = transitionRef.current;
      if (status.state === "running" && connection === "connected" && transition && now < transition.startedAt + transition.durationMs) {
        frame = requestAnimationFrame(animate);
      }
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [connection, draw, snapshot, status.state, transitionRef]);

  return (
    <div ref={hostRef} className="relative h-full min-h-[390px] overflow-hidden rounded-[20px] bg-[#0b1115]">
      <canvas ref={canvasRef} className="block h-full w-full" aria-label="Live SUMO intersection map" />
      <div className="pointer-events-none absolute left-4 top-4 rounded-lg border border-white/10 bg-[#0b1115]/80 px-3 py-2 backdrop-blur">
        <div className="font-mono text-[10px] uppercase tracking-[.18em] text-[#7f909b]">SUMO Cartesian</div>
        <div className="mt-1 text-xs text-[#b8c5cc]">{geometry.scenario_id}</div>
      </div>
      {!snapshot && status.state !== "idle" && (
        <div className="absolute inset-0 grid place-items-center bg-[#0b1115]/60 text-sm text-[#9cabb4]">Waiting for first SUMO snapshot…</div>
      )}
    </div>
  );
}
