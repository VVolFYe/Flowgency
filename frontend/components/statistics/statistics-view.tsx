"use client";

/**
 * Statistics page skeleton. The first option is the last run recorded from
 * Live Simulation (GET /api/analytics/runs/latest); the others come from the
 * analytics list (local SQLite copy of frontend/public/analytics/) and are
 * rendered by kind.
 */

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  isAnalyticsDocument,
  isAnalyticsList,
  isRecordedRun,
  isRecordedRunPair,
  type AnalyticsDocument,
  type AnalyticsListEntry,
  type RecordedRun,
  type RecordedRunPair,
} from "@/lib/contracts";
import { RecordedRunStatistics } from "./recorded-run-sections";
import { SimulationStatistics } from "./simulation-sections";
import { VisionStatistics } from "./vision-sections";

const LOADER_COMMAND = "python -m backend.analytics.load";
/** Cannot collide with an analytics id, which matches [A-Za-z0-9_.-]+. */
const LAST_RUN = "run:latest";
const NO_RUN_MESSAGE = "No simulation recorded yet - run one from Live Simulation";

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; value: T };
type LastRun = Load<{ run: RecordedRun; pair: RecordedRunPair | null }> | { status: "empty" };

function errorMessage(reason: unknown, what: string) {
  if (reason instanceof ApiError && reason.status === 503) {
    return `The analytics database is not available. Check FLOWGENCY_ANALYTICS_DB on the backend (unset = local SQLite), run ${LOADER_COMMAND} from the repository root if it is empty, then reload this page.`;
  }
  if (reason instanceof ApiError && reason.status === 404) {
    return `${what} is not in the analytics database. Re-run ${LOADER_COMMAND} after regenerating the JSON files.`;
  }
  return reason instanceof Error ? reason.message : "Unknown error";
}

async function fetchLastRun(signal: AbortSignal) {
  const run = await api.latestRun(signal);
  if (!isRecordedRun(run)) throw new Error("GET /api/analytics/runs/latest does not match the recorded run contract");
  let pair: RecordedRunPair | null = null;
  try {
    const value = await api.latestRunPair(run.run.scenario_id, signal);
    if (isRecordedRunPair(value)) pair = value;
  } catch (reason) {
    if (signal.aborted) throw reason;
    // The comparison is optional; the last run is still shown without it.
  }
  return { run, pair };
}

export function StatisticsView() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [index, setIndex] = useState<Load<AnalyticsListEntry[]>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string>(LAST_RUN);
  const [lastRun, setLastRun] = useState<LastRun>({ status: "loading" });
  const [dataset, setDataset] = useState<Load<AnalyticsDocument> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api.analyticsList(controller.signal)
      .then((value) => {
        if (!isAnalyticsList(value)) throw new Error("GET /api/analytics does not match the analytics list contract");
        setIndex({ status: "ready", value });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setIndex({ status: "error", message: errorMessage(reason, "The analytics list") });
      });
    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    if (selectedId !== LAST_RUN) return;
    const controller = new AbortController();
    fetchLastRun(controller.signal)
      .then((value) => setLastRun({ status: "ready", value }))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        // 404: nothing recorded; 503: the database file does not exist yet (the first run creates it).
        if (reason instanceof ApiError && (reason.status === 404 || reason.status === 503)) setLastRun({ status: "empty" });
        else setLastRun({ status: "error", message: reason instanceof Error ? reason.message : "Unknown error" });
      });
    return () => controller.abort();
  }, [selectedId, refreshKey]);

  const entry = index.status === "ready" ? index.value.find((item) => item.id === selectedId) ?? null : null;

  useEffect(() => {
    if (!entry) return;
    const controller = new AbortController();
    api.analyticsEntry(entry.id, controller.signal)
      .then((value) => {
        if (!isAnalyticsDocument(value, entry.kind)) throw new Error(`${entry.id} does not match the ${entry.kind} analytics contract`);
        setDataset({ status: "ready", value });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setDataset({ status: "error", message: errorMessage(reason, `“${entry.label}”`) });
      });
    return () => controller.abort();
  }, [entry]);

  function select(id: string) {
    if (id === LAST_RUN) setLastRun({ status: "loading" });
    else setDataset({ status: "loading" });
    setSelectedId(id);
  }

  function refresh() {
    if (selectedId === LAST_RUN) setLastRun({ status: "loading" });
    else setDataset({ status: "loading" });
    setRefreshKey((key) => key + 1);
  }

  return (
    <div className="statistics-page">
      <header className="statistics-page-header">
        <h1 className="text-2xl font-semibold">Statistics</h1>
        <p className="mt-1 text-sm opacity-70">The last run recorded from Live Simulation, plus results loaded from the local analytics database: SUMO fixed-vs-adaptive simulations and camera gate counts. Unknown values are shown as —.</p>
      </header>

      <div className="statistics-selector mt-6 flex flex-wrap items-center gap-2">
        <label htmlFor="statistics-dataset" className="text-sm">Dataset</label>
        <select
          id="statistics-dataset"
          value={selectedId}
          onChange={(event) => select(event.target.value)}
          className="rounded-lg border border-white/10 bg-transparent px-2 py-1 text-sm"
        >
          <option value={LAST_RUN} className="text-black">Last simulation</option>
          {index.status === "ready" && (["simulation", "vision"] as const).map((kind) => {
            const options = index.value.filter((item) => item.kind === kind);
            return options.length === 0 ? null : (
              <optgroup key={kind} label={kind === "simulation" ? "Simulation (SUMO)" : "Vision (camera)"}>
                {options.map((item) => <option key={item.id} value={item.id} className="text-black">{item.label}</option>)}
              </optgroup>
            );
          })}
        </select>
        <button type="button" onClick={refresh} className="rounded-lg border border-white/10 px-2 py-1 text-sm">Refresh</button>
      </div>
      {index.status === "loading" && <p role="status" className="mt-2 text-xs opacity-70">Loading statistics index…</p>}
      {index.status === "error" && <p className="mt-2 text-xs opacity-70">Analytics files unavailable: {index.message}</p>}
      {index.status === "ready" && index.value.length === 0 && (
        <p className="mt-2 text-xs opacity-70">No analytics files are loaded. Generate the JSON files and run {LOADER_COMMAND} (see frontend/public/analytics/README.md).</p>
      )}

      {selectedId === LAST_RUN && (
        <>
          {lastRun.status === "loading" && <p role="status" className="mt-6 text-sm">Loading the last simulation…</p>}
          {lastRun.status === "empty" && <p className="mt-6 text-sm">{NO_RUN_MESSAGE}</p>}
          {lastRun.status === "error" && <p role="alert" className="mt-6 text-sm">Could not load the last simulation: {lastRun.message}</p>}
          {lastRun.status === "ready" && <RecordedRunStatistics run={lastRun.value.run} pair={lastRun.value.pair} />}
        </>
      )}

      {selectedId !== LAST_RUN && !entry && index.status !== "loading" && (
        <p role="alert" className="mt-6 text-sm">This dataset is no longer available. Choose another one.</p>
      )}
      {selectedId !== LAST_RUN && entry && (
        <>
          {dataset?.status === "loading" && <p role="status" className="mt-6 text-sm">Loading {entry?.label ?? "dataset"}…</p>}
          {dataset?.status === "error" && <p role="alert" className="mt-6 text-sm">Could not load {entry?.label ?? "dataset"}: {dataset.message}</p>}
          {dataset?.status === "ready" && (dataset.value.kind === "simulation"
            ? <SimulationStatistics data={dataset.value} />
            : <VisionStatistics data={dataset.value} />)}
        </>
      )}
    </div>
  );
}
