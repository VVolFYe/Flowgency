"use client";

import Link from "next/link";
import { SimulationProvider, useSimulation } from "@/components/simulation/simulation-provider";
import { SimulationMap as SimulationCanvas } from "@/components/simulation/simulation-map";

function Preview() {
  const { geometry, snapshot, status, connection, selectedScenario, loading, error } = useSimulation();
  const running = status.state === "running";
  return (
    <div className="product-window">
      <div className="product-toolbar">
        <div className="product-name"><span className="window-status" data-live={running && connection === "connected"} />Simulation</div>
        <span className="product-scenario">{selectedScenario?.display_name ?? "Connecting to SUMO"}</span>
        <Link href="/simulation">Open live view <span aria-hidden="true">↗</span></Link>
      </div>
      <div className="product-canvas">
        {geometry ? <SimulationCanvas geometry={geometry} snapshot={snapshot} status={status} connection={connection} scenario={selectedScenario} /> :
          <div className="preview-message" role="status">{loading ? "Loading the road network…" : error ?? "The simulation backend is unavailable."}</div>}
      </div>
      <div className="product-bottom">
        <span>{connection === "connected" ? running ? "Simulation running" : "Road network ready" : "Connecting to backend"}</span>
        <span>{snapshot ? `${snapshot.vehicles?.length ?? "—"} vehicles · ${snapshot.simulation_time_s.toFixed(0)}s simulated` : "Start a run from the operator workspace"}</span>
      </div>
    </div>
  );
}

export function HomeSimulation() {
  return <SimulationProvider><Preview /></SimulationProvider>;
}
