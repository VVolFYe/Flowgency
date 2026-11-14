"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { useSimulation } from "./simulation-provider";

interface CompletedRun {
  waiting: number;
  arrived: number;
  runId: string;
}
interface RunPair { fixed?: CompletedRun; adaptive?: CompletedRun }
const STORAGE_KEY = "flowgency-completed-comparisons-v1";
const UPDATED_EVENT = "flowgency-comparisons-updated";

function subscribe(callback: () => void) {
  window.addEventListener(UPDATED_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(UPDATED_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}
function readStorage() {
  try { return sessionStorage.getItem(STORAGE_KEY) ?? "{}"; } catch { return "{}"; }
}

export function RunComparison() {
  const { selectedScenarioId, status, snapshot } = useSimulation();
  const storedRuns = useSyncExternalStore(subscribe, readStorage, () => "{}");
  const runs = useMemo(() => {
    try {
      const stored: unknown = JSON.parse(storedRuns);
      if (stored && typeof stored === "object" && !Array.isArray(stored)) {
        const valid: Record<string, RunPair> = {};
        for (const [scenario, pair] of Object.entries(stored)) {
          if (!pair || typeof pair !== "object") continue;
          const entries: RunPair = {};
          for (const mode of ["fixed", "adaptive"] as const) {
            const run = (pair as RunPair)[mode];
            if (run && Number.isFinite(run.waiting) && run.waiting >= 0 &&
                Number.isInteger(run.arrived) && run.arrived > 0 && typeof run.runId === "string") {
              entries[mode] = run;
            }
          }
          valid[scenario] = entries;
        }
        return valid;
      }
    } catch { /* Comparison history is optional. */ }
    return {} as Record<string, RunPair>;
  }, [storedRuns]);
  useEffect(() => {
    const mode = status.control_mode;
    const metrics = snapshot?.metrics;
    if (status.state !== "finished" || !snapshot || !metrics ||
        (mode !== "fixed" && mode !== "adaptive") ||
        metrics.active_vehicle_count !== 0 || metrics.arrived_vehicle_count <= 0 ||
        metrics.arrived_vehicle_count !== metrics.departed_vehicle_count) return;
    const scenario = snapshot.scenario_selection_id;
    if (!scenario) return;
    if (runs[scenario]?.[mode]?.runId !== snapshot.run_id) {
      const updated = {
        ...runs,
        [scenario]: { ...runs[scenario], [mode]: {
          waiting: metrics.total_waiting_time_s, arrived: metrics.arrived_vehicle_count, runId: snapshot.run_id,
        } },
      };
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
        window.dispatchEvent(new Event(UPDATED_EVENT));
      } catch { /* Storage may be unavailable. */ }
    }
  }, [status.state, status.control_mode, snapshot, runs]);
  const pair = runs[selectedScenarioId];
  const fixed = pair?.fixed;
  const adaptive = pair?.adaptive;
  const comparable = fixed && adaptive && fixed.arrived === adaptive.arrived;
  const saved = comparable ? fixed.waiting - adaptive.waiting : null;
  const percent = comparable && fixed.waiting > 0 ? 100 * (fixed.waiting - adaptive.waiting) / fixed.waiting : null;
  return (
    <section className="surface comparison-panel" aria-label="Fixed and adaptive comparison">
      <h2>Fixed vs Adaptive</h2>
      <p className="comparison-source">Completed runs · this browser tab</p>
      <div className="comparison-values">
        <div><span>Fixed wait</span><strong>{fixed ? `${fixed.waiting.toFixed(0)}s` : "—"}</strong></div>
        <div><span>Adaptive wait</span><strong>{adaptive ? `${adaptive.waiting.toFixed(0)}s` : "—"}</strong></div>
      </div>
      {saved != null ? (
        <p className="comparison-result" data-improved={saved >= 0}>
          <strong>{percent == null ? `${Math.abs(saved).toFixed(0)}s` : `${Math.abs(percent).toFixed(1)}%`}</strong>
          <span>{saved >= 0 ? "less waiting" : "more waiting"}<small>{Math.abs(saved).toFixed(0)} vehicle-seconds · {fixed?.arrived} arrivals each</small></span>
        </p>
      ) : (
        <p className="comparison-hint">{fixed && adaptive ? "Arrival counts differ. Complete comparable runs to calculate savings." : "Complete a Fixed and an Adaptive run of this scenario to compare waiting time."}</p>
      )}
    </section>
  );
}
