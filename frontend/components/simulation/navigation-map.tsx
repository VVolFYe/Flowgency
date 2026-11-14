"use client";

import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import type { NetworkGeometry, SimulationSnapshot, SimulationStatus, Vehicle } from "@/lib/contracts";
import { demonstrationBuildings, mapCoordinates, roadFeatures, signalFeatures } from "@/lib/map-geometry";
import { registerVehicleIcons } from "./vehicle-icons";

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };
const LOCAL_STYLE: StyleSpecification = {
  version: 8, sources: {},
  layers: [{ id: "ground", type: "background", paint: { "background-color": "#cad8bc" } }],
};

export function NavigationMap({ geometry, snapshot, status, onTechnical }: {
  geometry: NetworkGeometry;
  snapshot: SimulationSnapshot | null;
  status: SimulationStatus;
  onTechnical: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const latest = useRef(snapshot);
  const renderedVehicles = useRef<Vehicle[]>([]);
  const renderedRun = useRef<string | undefined>(undefined);
  const [ready, setReady] = useState(false);
  const [tilted, setTilted] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [following, setFollowing] = useState<string | null>(null);
  const synthetic = geometry.coordinate_system === "synthetic_cartesian_metres";

  useEffect(() => { latest.current = snapshot; }, [snapshot]);

  useEffect(() => {
    if (!host.current) return;
    let map: MapLibreMap;
    try {
      const coordinates = mapCoordinates(geometry);
      const b = geometry.bounds;
      const bounds = new maplibregl.LngLatBounds(coordinates(b.min_x_m, b.min_y_m), coordinates(b.max_x_m, b.max_y_m));
      maplibregl.setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);
      map = new maplibregl.Map({
        container: host.current,
        style: synthetic ? LOCAL_STYLE : "https://tiles.openfreemap.org/styles/liberty",
        center: bounds.getCenter(), zoom: synthetic ? 17 : 14, pitch: 45,
        maxPitch: 60, attributionControl: { compact: true },
        canvasContextAttributes: { antialias: true },
      });
      mapRef.current = map;
      map.on("pitchend", () => setTilted(map.getPitch() > 1));
      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
      map.on("error", event => {
        console.warn("Map renderer:", event.error.message);
        setProblem("Some map resources could not load. The technical view is available.");
      });
      map.on("load", () => {
        if (synthetic) {
          map.addSource("surroundings", { type: "geojson", data: demonstrationBuildings(geometry) });
          map.addLayer({ id: "surroundings", type: "fill-extrusion", source: "surroundings",
            paint: { "fill-extrusion-color": "#e9e0ca", "fill-extrusion-height": ["get", "height"], "fill-extrusion-opacity": .95 } });
        }
        registerVehicleIcons(map);
        map.addSource("sumo-roads", { type: "geojson", data: roadFeatures(geometry) });
        map.addLayer({ id: "sumo-sidewalks", type: "line", source: "sumo-roads",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#c1c5bd", "line-width":
            ["interpolate", ["exponential", 2], ["zoom"], 10, ["*", ["+", ["get", "width"], 2], .01], 22, ["*", ["+", ["get", "width"], 2], 40.96]] } });
        map.addLayer({ id: "sumo-roads", type: "line", source: "sumo-roads",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#48535b", "line-opacity": .95, "line-width":
            ["interpolate", ["exponential", 2], ["zoom"], 10, ["*", ["get", "width"], .01], 22, ["*", ["get", "width"], 40.96]] } });
        map.addLayer({ id: "sumo-markings", type: "line", source: "sumo-roads", minzoom: 17,
          paint: { "line-color": "#f5edc9", "line-width": .6, "line-opacity": .65, "line-dasharray": [6, 8] } });
        map.addSource("signals", { type: "geojson", data: signalFeatures(geometry, latest.current) });
        map.addLayer({ id: "priority-signals", type: "circle", source: "signals",
          filter: ["==", ["get", "priority"], true],
          paint: { "circle-radius": 10, "circle-color": "#ffb653", "circle-opacity": .15,
            "circle-stroke-color": "#b94604", "circle-stroke-width": 2 } });
        map.addLayer({ id: "signals", type: "circle", source: "signals", paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 2.5, 18, 6],
          "circle-color": ["get", "color"], "circle-stroke-color": "#1b2529", "circle-stroke-width": 2,
          "circle-pitch-alignment": "viewport",
        } });
        map.addSource("vehicles", { type: "geojson", data: EMPTY });
        map.addLayer({ id: "priority", type: "circle", source: "vehicles", filter: ["==", ["get", "priority"], true],
          paint: { "circle-radius": 18, "circle-color": "#ffb653", "circle-opacity": .2,
            "circle-stroke-color": "#b94604", "circle-stroke-width": 2 } });
        map.addLayer({ id: "vehicles", type: "symbol", source: "vehicles", layout: {
          "icon-image": ["get", "icon"], "icon-size": ["interpolate", ["linear"], ["zoom"], 13, .24, 17, .65, 20, 1.2],
          "icon-rotate": ["get", "angle"], "icon-rotation-alignment": "map", "icon-pitch-alignment": "map",
          "icon-allow-overlap": true, "icon-ignore-placement": true,
        } });
        const popup = new maplibregl.Popup({ closeButton: false, offset: 12 });
        map.on("mousemove", "signals", event => {
          const feature = event.features?.[0];
          if (!feature || feature.geometry.type !== "Point") return;
          const label = document.createElement("div");
          label.textContent = `${feature.properties.tls} · link ${feature.properties.link} · ${feature.properties.state}`;
          popup.setLngLat(feature.geometry.coordinates as [number, number]).setDOMContent(label).addTo(map);
        });
        map.on("mouseleave", "signals", () => popup.remove());
        map.on("click", "vehicles", event => {
          const feature = event.features?.[0];
          if (!feature || feature.geometry.type !== "Point") return;
          const label = document.createElement("div");
          label.textContent = `${feature.properties.id} · ${feature.properties.type} · ${Number(feature.properties.speed).toFixed(1)} m/s`;
          const follow = document.createElement("button");
          follow.className = "map-follow-button";
          follow.textContent = "Follow vehicle";
          follow.addEventListener("click", () => {
            setFollowing(String(feature.properties.id));
            popup.remove();
          });
          label.appendChild(follow);
          popup.setLngLat(feature.geometry.coordinates as [number, number]).setDOMContent(label).addTo(map);
        });
        map.on("dragstart", () => setFollowing(null));
        map.fitBounds(bounds, { padding: 55, duration: 0, maxZoom: 18 });
        if (synthetic) map.setZoom(Math.min(map.getZoom() + 1, 19));
        setReady(true);
      });
      const resize = new ResizeObserver(() => map.resize());
      resize.observe(host.current);
      return () => { resize.disconnect(); map.remove(); mapRef.current = null; };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Map rendering is unavailable.";
      queueMicrotask(() => setProblem(message));
    }
  }, [geometry, synthetic]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("signals") as GeoJSONSource)?.setData(signalFeatures(geometry, snapshot));
    const coordinates = mapCoordinates(geometry);
    const target = snapshot?.vehicles ?? [];
    const priorityVehicles = new Set(snapshot?.emergency_events
      ?.filter(event => event.priority_supported && event.state === "priority_active")
      .map(event => event.emergency_vehicle_id) ??
      (snapshot?.emergency_priority?.active_vehicle_id ? [snapshot.emergency_priority.active_vehicle_id] : []));
    const source = new Map(
      renderedRun.current === snapshot?.run_id ? renderedVehicles.current.map(v => [v.vehicle_id, v]) : [],
    );
    renderedRun.current = snapshot?.run_id;
    const start = performance.now();
    const animate = status.state === "running" && source.size > 0;
    let frame = 0, last = -Infinity;
    const draw = (now: number) => {
      const fraction = animate ? Math.min(1, (now - start) / 220) : 1;
      if (now - last >= 45 || fraction === 1) {
        last = now;
        const current = target.map(vehicle => {
          const previous = source.get(vehicle.vehicle_id) ?? vehicle;
          const angle = ((vehicle.angle_deg - previous.angle_deg + 540) % 360) - 180;
          return { ...vehicle,
            x_m: previous.x_m + (vehicle.x_m - previous.x_m) * fraction,
            y_m: previous.y_m + (vehicle.y_m - previous.y_m) * fraction,
            angle_deg: previous.angle_deg + angle * fraction };
        });
        renderedVehicles.current = current;
        const followed = current.find(vehicle => vehicle.vehicle_id === following);
        if (followed) map.jumpTo({ center: coordinates(followed.x_m, followed.y_m), zoom: Math.max(17, map.getZoom()) });
        const data: FeatureCollection = { type: "FeatureCollection", features: current.map(v => ({
          type: "Feature", properties: {
            id: v.vehicle_id, type: v.vehicle_type, speed: v.speed_mps, angle: v.angle_deg,
            icon: `flowgency-${["ambulance", "police", "fire_brigade"].includes(v.vehicle_type) ? v.vehicle_type : v.vehicle_type.includes("bus") ? "bus" : "car"}`,
            priority: priorityVehicles.has(v.vehicle_id),
          }, geometry: { type: "Point", coordinates: coordinates(v.x_m, v.y_m) },
        })) };
        (map.getSource("vehicles") as GeoJSONSource)?.setData(data);
      }
      if (fraction < 1) frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [geometry, ready, snapshot, status.state, following]);

  const fit = () => {
    setFollowing(null);
    const b = geometry.bounds, coordinates = mapCoordinates(geometry);
    mapRef.current?.fitBounds([coordinates(b.min_x_m, b.min_y_m), coordinates(b.max_x_m, b.max_y_m)],
      { padding: 55, maxZoom: 18, duration: 500 });
  };
  return (
    <div className="navigation-map">
      <div ref={host} className="navigation-map-host" aria-label="SUMO vehicles on an interactive road map" />
      <div className="map-camera-controls">
        {following && <button onClick={() => setFollowing(null)}>Stop following</button>}
        <button onClick={fit} disabled={!ready}>Fit network</button>
        <button disabled={!ready} aria-pressed={tilted} onClick={() => {
          mapRef.current?.easeTo({ pitch: tilted ? 0 : 45, duration: 500 });
          setTilted(!tilted);
        }}>{tilted ? "View from above" : "Tilt map"}</button>
      </div>
      {synthetic && <p className="map-scene-label">Demonstration surroundings · SUMO road geometry</p>}
      {problem && <div className="map-resource-error" role="status">{problem} <button onClick={onTechnical}>Open technical view</button></div>}
      {!ready && !problem && <div className="map-loading" role="status">Loading the road map…</div>}
    </div>
  );
}
