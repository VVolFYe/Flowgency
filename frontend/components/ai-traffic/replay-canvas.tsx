"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { NetworkGeometry, Point } from "@/lib/contracts";
import { frameAtTime, replaySignalColor, sourceStatus, type ReplayStream } from "@/lib/ai-replay";

interface Size { width: number; height: number }

function configureCanvas(canvas: HTMLCanvasElement, size: Size) {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.round(size.width * ratio);
  const height = Math.round(size.height * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const context = canvas.getContext("2d");
  context?.setTransform(ratio, 0, 0, ratio, 0, 0);
  return context;
}

function projector(geometry: NetworkGeometry, size: Size) {
  const { bounds } = geometry;
  const padding = Math.max(20, Math.min(size.width, size.height) * 0.07);
  const worldWidth = Math.max(1, bounds.max_x_m - bounds.min_x_m);
  const worldHeight = Math.max(1, bounds.max_y_m - bounds.min_y_m);
  const scale = Math.max(0.001, Math.min(
    Math.max(1, size.width - padding * 2) / worldWidth,
    Math.max(1, size.height - padding * 2) / worldHeight,
  ));
  const centerX = (bounds.min_x_m + bounds.max_x_m) / 2;
  const centerY = (bounds.min_y_m + bounds.max_y_m) / 2;
  return {
    scale,
    screen: (point: Point) => ({
      x: size.width / 2 + (point.x_m - centerX) * scale,
      y: size.height / 2 - (point.y_m - centerY) * scale,
    }),
  };
}

function path(context: CanvasRenderingContext2D, shape: Point[], screen: (point: Point) => { x: number; y: number }) {
  context.beginPath();
  shape.forEach((point, index) => {
    const position = screen(point);
    if (index === 0) context.moveTo(position.x, position.y);
    else context.lineTo(position.x, position.y);
  });
}

export function ReplayCanvas({ geometry, replay, timeS, playing, accent }: {
  geometry: NetworkGeometry;
  replay: ReplayStream;
  timeS: number;
  playing: boolean;
  accent: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const staticRef = useRef<HTMLCanvasElement>(null);
  const dynamicRef = useRef<HTMLCanvasElement>(null);
  const sizeRef = useRef<Size>({ width: 0, height: 0 });
  const [sizeRevision, setSizeRevision] = useState(0);
  const sampled = useMemo(() => frameAtTime(replay, timeS), [replay, timeS]);
  const currentLight = useMemo(
    () => sampled.traffic_lights.find((item) => item.traffic_light_id === "demo_01"),
    [sampled],
  );
  const lanes = useMemo(
    () => geometry.edges.flatMap((edge) => edge.lanes.map((lane) => ({ lane, internal: edge.is_internal }))),
    [geometry],
  );
  const laneById = useMemo(() => new Map(lanes.map(({ lane }) => [lane.lane_id, lane])), [lanes]);

  const drawStatic = useCallback(() => {
    const canvas = staticRef.current;
    const size = sizeRef.current;
    if (!canvas || size.width <= 0 || size.height <= 0) return;
    const context = configureCanvas(canvas, size);
    if (!context) return;
    context.clearRect(0, 0, size.width, size.height);
    context.fillStyle = "#091014";
    context.fillRect(0, 0, size.width, size.height);
    const { screen, scale } = projector(geometry, size);
    geometry.junctions.forEach((junction) => {
      if (junction.shape.length < 3) return;
      path(context, junction.shape, screen);
      context.closePath();
      context.fillStyle = junction.type === "traffic_light" ? "#243038" : "#172128";
      context.fill();
    });
    lanes.forEach(({ lane, internal }) => {
      if (lane.shape.length < 2) return;
      path(context, lane.shape, screen);
      context.lineCap = "round";
      context.lineJoin = "round";
      context.lineWidth = Math.min(13, Math.max(internal ? 1 : 2, lane.width_m * scale));
      context.strokeStyle = internal ? "#445159" : "#303d45";
      context.stroke();
      if (!internal) {
        context.setLineDash([7, 7]);
        context.lineWidth = 0.7;
        context.strokeStyle = "rgba(225,235,240,.26)";
        context.stroke();
        context.setLineDash([]);
      }
    });
  }, [geometry, lanes]);

  const drawDynamic = useCallback(() => {
    const canvas = dynamicRef.current;
    const size = sizeRef.current;
    if (!canvas || size.width <= 0 || size.height <= 0) return;
    const context = configureCanvas(canvas, size);
    if (!context) return;
    context.clearRect(0, 0, size.width, size.height);
    const { screen, scale } = projector(geometry, size);
    const linksByLane = new Map<string, typeof geometry.controlled_links>();
    geometry.controlled_links.forEach((link) => {
      linksByLane.set(link.from_lane, [...(linksByLane.get(link.from_lane) ?? []), link]);
    });
    const junction = geometry.junctions.find((item) => item.junction_id === "demo_01");
    linksByLane.forEach((links, laneId) => {
      const lane = laneById.get(laneId);
      if (!lane || lane.shape.length < 2 || !junction) return;
      const points = [...lane.shape].sort((a, b) =>
        Math.hypot(a.x_m - junction.x_m, a.y_m - junction.y_m) -
        Math.hypot(b.x_m - junction.x_m, b.y_m - junction.y_m));
      const stop = points[0];
      const previous = points[1];
      const length = Math.max(0.001, Math.hypot(previous.x_m - stop.x_m, previous.y_m - stop.y_m));
      const ux = (previous.x_m - stop.x_m) / length;
      const uy = (previous.y_m - stop.y_m) / length;
      links.sort((a, b) => a.link_index - b.link_index).forEach((link, index) => {
        const spread = (index - (links.length - 1) / 2) * 3.4;
        const position = screen({ x_m: stop.x_m + ux * 5 - uy * spread, y_m: stop.y_m + uy * 5 + ux * spread });
        const color = replaySignalColor(currentLight?.state[link.link_index]);
        context.beginPath();
        context.arc(position.x, position.y, 7, 0, Math.PI * 2);
        context.fillStyle = "#050b0e";
        context.fill();
        context.lineWidth = 1.5;
        context.strokeStyle = "#85949d";
        context.stroke();
        context.beginPath();
        context.arc(position.x, position.y, 4, 0, Math.PI * 2);
        context.fillStyle = color;
        context.shadowColor = color;
        context.shadowBlur = 10;
        context.fill();
        context.shadowBlur = 0;
      });
    });
    sampled.vehicles.forEach((vehicle) => {
      const position = screen(vehicle);
      const length = Math.min(13, Math.max(5, 4.6 * scale));
      const width = Math.min(7, Math.max(2.8, 2 * scale));
      context.save();
      context.translate(position.x, position.y);
      context.rotate(vehicle.angle_deg * Math.PI / 180);
      context.beginPath();
      context.roundRect(-width / 2, -length / 2, width, length, Math.min(2, width / 2));
      context.fillStyle = accent;
      context.shadowColor = accent;
      context.shadowBlur = 5;
      context.fill();
      context.shadowBlur = 0;
      context.beginPath();
      context.arc(0, -length * 0.3, Math.max(0.8, width * 0.18), 0, Math.PI * 2);
      context.fillStyle = "#ffffff";
      context.fill();
      context.restore();
    });
  }, [accent, currentLight?.state, geometry, laneById, sampled]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const resize = new ResizeObserver(([entry]) => {
      sizeRef.current = { width: entry.contentRect.width, height: entry.contentRect.height };
      setSizeRevision((revision) => revision + 1);
    });
    resize.observe(host);
    return () => resize.disconnect();
  }, []);

  useEffect(() => { drawStatic(); }, [drawStatic, sizeRevision]);
  useEffect(() => { drawDynamic(); }, [drawDynamic, sizeRevision]);

  const finished = timeS >= replay.durationS;
  return (
    <div ref={hostRef} className="relative h-full min-h-52 overflow-hidden bg-[#091014]">
      <canvas ref={staticRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />
      <canvas ref={dynamicRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-label="Recorded SUMO vehicle and traffic-light replay" />
      <div className="pointer-events-none absolute left-3 top-3 rounded-lg border border-white/10 bg-[#071014]/90 px-2.5 py-1.5 text-[10px] text-[#c7d5dc] backdrop-blur">
        <span className="font-mono">{sampled.vehicles.length} vehicles</span>
        <span className="mx-1.5 text-[#667781]">·</span>
        <span>{currentLight?.phase_id ?? "TLS unavailable"}</span>
      </div>
      <div className={`pointer-events-none absolute bottom-3 right-3 rounded-full border px-2.5 py-1 text-[10px] font-medium ${finished ? "border-[#7cf2ad]/30 bg-[#11291c]/90 text-[#a2f4be]" : "border-white/10 bg-[#071014]/90 text-[#c7d5dc]"}`}>
        {finished ? "Simulation finished" : playing ? sourceStatus(timeS, replay.durationS, "simulation") : "Paused"}
      </div>
    </div>
  );
}
