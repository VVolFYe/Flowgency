"use client";

/**
 * Statistics page skeleton: loads the static index, lets the user pick a file
 * and renders it by kind. Data comes only from frontend/public/analytics/.
 */

import { useEffect, useState } from "react";
import {
  isAnalyticsDocument,
  isAnalyticsIndex,
  type AnalyticsDocument,
  type AnalyticsIndexEntry,
} from "@/lib/contracts";
import { SimulationStatistics } from "./simulation-sections";
import { VisionStatistics } from "./vision-sections";

const ANALYTICS_BASE = "/analytics";

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; value: T };

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "Unknown error";
}

export function StatisticsView() {
  const [index, setIndex] = useState<Load<AnalyticsIndexEntry[]>>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dataset, setDataset] = useState<Load<AnalyticsDocument> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchJson(`${ANALYTICS_BASE}/index.json`, controller.signal)
      .then((value) => {
        if (!isAnalyticsIndex(value)) throw new Error("index.json does not match the analytics index contract");
        setIndex({ status: "ready", value });
        if (value.length > 0) {
          setSelectedId(value[0].id);
          setDataset({ status: "loading" });
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setIndex({ status: "error", message: errorMessage(reason) });
      });
    return () => controller.abort();
  }, []);

  const entry = index.status === "ready" ? index.value.find((item) => item.id === selectedId) ?? null : null;

  useEffect(() => {
    if (!entry) return;
    const controller = new AbortController();
    fetchJson(`${ANALYTICS_BASE}/${entry.file}`, controller.signal)
      .then((value) => {
        if (!isAnalyticsDocument(value, entry.kind)) throw new Error(`${entry.file} does not match the ${entry.kind} analytics contract`);
        setDataset({ status: "ready", value });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setDataset({ status: "error", message: errorMessage(reason) });
      });
    return () => controller.abort();
  }, [entry]);

  return (
    <div className="statistics-page">
      <header className="statistics-page-header">
        <h1 className="text-2xl font-semibold">Statistics</h1>
        <p className="mt-1 text-sm opacity-70">Committed static results: SUMO fixed-vs-adaptive simulations and camera gate counts. Unknown values are shown as —.</p>
      </header>

      {index.status === "loading" && <p role="status" className="mt-6 text-sm">Loading statistics index…</p>}
      {index.status === "error" && <p role="alert" className="mt-6 text-sm">Could not load the statistics index: {index.message}</p>}
      {index.status === "ready" && index.value.length === 0 && (
        <p className="mt-6 text-sm">No statistics files have been generated yet. See frontend/public/analytics/README.md.</p>
      )}

      {index.status === "ready" && index.value.length > 0 && (
        <div className="statistics-selector mt-6">
          <label htmlFor="statistics-dataset" className="mr-2 text-sm">Dataset</label>
          <select
            id="statistics-dataset"
            value={selectedId ?? ""}
            onChange={(event) => { setDataset({ status: "loading" }); setSelectedId(event.target.value); }}
            className="rounded-lg border border-white/10 bg-transparent px-2 py-1 text-sm"
          >
            {(["simulation", "vision"] as const).map((kind) => {
              const options = index.value.filter((item) => item.kind === kind);
              return options.length === 0 ? null : (
                <optgroup key={kind} label={kind === "simulation" ? "Simulation (SUMO)" : "Vision (camera)"}>
                  {options.map((item) => <option key={item.id} value={item.id} className="text-black">{item.label}</option>)}
                </optgroup>
              );
            })}
          </select>
        </div>
      )}

      {dataset?.status === "loading" && <p role="status" className="mt-6 text-sm">Loading {entry?.label ?? "dataset"}…</p>}
      {dataset?.status === "error" && <p role="alert" className="mt-6 text-sm">Could not load {entry?.label ?? "dataset"}: {dataset.message}</p>}
      {dataset?.status === "ready" && (dataset.value.kind === "simulation"
        ? <SimulationStatistics data={dataset.value} />
        : <VisionStatistics data={dataset.value} />)}
    </div>
  );
}
