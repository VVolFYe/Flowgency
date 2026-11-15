"use client";

import dynamic from "next/dynamic";
import { useState, type ComponentProps } from "react";
import { SimulationCanvas } from "@/components/simulation-canvas";

const NavigationMap = dynamic(() => import("./navigation-map").then(module => module.NavigationMap), {
  ssr: false, loading: () => <div className="map-loading">Loading map renderer…</div>,
});

export function SimulationMap(props: ComponentProps<typeof SimulationCanvas>) {
  const [technical, setTechnical] = useState(false);
  return (
    <div className="simulation-map-frame" data-technical={technical}>
      {technical ? <SimulationCanvas {...props} /> :
        <NavigationMap key={props.geometry.scenario_selection_id} geometry={props.geometry} snapshot={props.snapshot} status={props.status} onTechnical={() => setTechnical(true)} />}
      <div className="map-view-switch" role="group" aria-label="Map presentation">
        <button aria-pressed={!technical} onClick={() => setTechnical(false)}>Map</button>
        <button aria-pressed={technical} onClick={() => setTechnical(true)}>Technical</button>
      </div>
    </div>
  );
}
