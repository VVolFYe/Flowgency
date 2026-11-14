"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { SiteNav } from "@/components/site-nav";

const BENCHMARK_URL = "/benchmarks/london-unbalanced-fixed-vs-adaptive.json";

type PairMetric = {
  fixed: number;
  adaptive: number;
  absolute_improvement: number;
  percentage_improvement: number;
};

type RunValidation = {
  passed: boolean;
  departed: number;
  arrived: number;
  completed: number;
  unfinished: number;
  duplicate_tripinfo_ids: number;
  collisions: number;
  teleports: number;
  process_exit_code: number;
  terminated_by_step_limit: boolean;
};

type BenchmarkSnapshot = {
  schema_version: string;
  snapshot_schema_version: string;
  benchmark: string;
  scenario_id: string;
  scenario_name: string;
  provenance: {
    authoritative_report: string;
    config: string;
    network: string;
    routes: string;
    adaptive_manifest: string;
    seed: number;
    expected_vehicle_count: number;
    expected_vehicle_ids_sha256: string;
    snapshot_created_on: string;
  };
  experiment: {
    fixed_label: string;
    adaptive_label: string;
    adaptive_intersection_id: string;
    adaptive_traffic_light_id: string;
    adaptive_scope: string;
    controlled_difference: string;
  };
  validation: {
    passed: boolean;
    matched_vehicle_count: number;
    fixed: RunValidation;
    adaptive: RunValidation;
  };
  runs: {
    fixed: { steps: number; cycle_decisions: number };
    adaptive: { steps: number; cycle_decisions: number };
  };
  metrics: {
    total_waiting_time_s: PairMetric;
    average_waiting_time_s: PairMetric;
    total_time_loss_s: PairMetric;
    average_time_loss_s: PairMetric;
    average_trip_duration_s: PairMetric;
  };
  limitations: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPairMetric(value: unknown): value is PairMetric {
  return isRecord(value)
    && isFiniteNumber(value.fixed)
    && isFiniteNumber(value.adaptive)
    && isFiniteNumber(value.absolute_improvement)
    && isFiniteNumber(value.percentage_improvement);
}

function isRunValidation(value: unknown): value is RunValidation {
  if (!isRecord(value) || typeof value.passed !== "boolean") return false;
  return [
    "departed", "arrived", "completed", "unfinished", "duplicate_tripinfo_ids",
    "collisions", "teleports", "process_exit_code",
  ].every((field) => isFiniteNumber(value[field]))
    && typeof value.terminated_by_step_limit === "boolean";
}

function isBenchmarkSnapshot(value: unknown): value is BenchmarkSnapshot {
  if (!isRecord(value) || value.schema_version !== "1.0" || value.snapshot_schema_version !== "1.0") return false;
  const provenance = value.provenance;
  const experiment = value.experiment;
  const validation = value.validation;
  const runs = value.runs;
  const metrics = value.metrics;
  if (!isRecord(provenance) || !isRecord(experiment) || !isRecord(validation) || !isRecord(runs) || !isRecord(metrics)) return false;
  if (!isRecord(runs.fixed) || !isRecord(runs.adaptive)) return false;
  return typeof value.scenario_id === "string"
    && typeof value.scenario_name === "string"
    && typeof provenance.authoritative_report === "string"
    && typeof provenance.config === "string"
    && typeof provenance.snapshot_created_on === "string"
    && isFiniteNumber(provenance.seed)
    && isFiniteNumber(provenance.expected_vehicle_count)
    && typeof experiment.adaptive_scope === "string"
    && typeof experiment.controlled_difference === "string"
    && typeof validation.passed === "boolean"
    && isFiniteNumber(validation.matched_vehicle_count)
    && isRunValidation(validation.fixed)
    && isRunValidation(validation.adaptive)
    && isFiniteNumber(runs.fixed.steps)
    && isFiniteNumber(runs.adaptive.steps)
    && isFiniteNumber(runs.fixed.cycle_decisions)
    && isFiniteNumber(runs.adaptive.cycle_decisions)
    && isPairMetric(metrics.total_waiting_time_s)
    && isPairMetric(metrics.average_waiting_time_s)
    && isPairMetric(metrics.total_time_loss_s)
    && isPairMetric(metrics.average_time_loss_s)
    && isPairMetric(metrics.average_trip_duration_s)
    && Array.isArray(value.limitations)
    && value.limitations.every((item) => typeof item === "string");
}

const wholeNumber = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const decimalNumber = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 3, maximumFractionDigits: 3 });

function valueLabel(value: number, decimals: number) {
  return `${decimals ? decimalNumber.format(value) : wholeNumber.format(value)} s`;
}

function differenceLabel(metric: PairMetric, decimals: number) {
  const adaptiveDifference = metric.adaptive - metric.fixed;
  if (Math.abs(adaptiveDifference) < 0.0005) return "No measured difference";
  const direction = adaptiveDifference > 0 ? "higher" : "lower";
  const value = decimals ? decimalNumber.format(Math.abs(adaptiveDifference)) : wholeNumber.format(Math.abs(adaptiveDifference));
  return `Adaptive is ${value} s (${Math.abs(metric.percentage_improvement).toFixed(2)}%) ${direction}`;
}

function ComparisonChart({
  title,
  description,
  metric,
  decimals = 0,
}: {
  title: string;
  description: string;
  metric: PairMetric;
  decimals?: number;
}) {
  const maximum = Math.max(metric.fixed, metric.adaptive, 1);
  const fixedWidth = `${(metric.fixed / maximum) * 100}%`;
  const adaptiveWidth = `${(metric.adaptive / maximum) * 100}%`;
  const adaptiveWorse = metric.adaptive > metric.fixed;

  return (
    <article className="rounded-[22px] border border-white/[.07] bg-[#10171c] p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-medium text-[#e1e9ed]">{title}</h2>
          <p className="mt-1 text-xs text-[#71818a]">{description}</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 font-mono text-[10px] ${adaptiveWorse ? "border-[#f0bc55]/25 bg-[#f0bc55]/10 text-[#f0bc55]" : "border-[#72e9a6]/25 bg-[#72e9a6]/10 text-[#72e9a6]"}`}>
          {adaptiveWorse ? "Adaptive higher" : "Adaptive lower"}
        </span>
      </div>

      <div className="mt-7 space-y-5">
        {[
          { label: "Fixed timing", value: metric.fixed, width: fixedWidth, color: "bg-[#718692]" },
          { label: "Adaptive J3", value: metric.adaptive, width: adaptiveWidth, color: adaptiveWorse ? "bg-[#d6a94d]" : "bg-[#72e9a6]" },
        ].map((bar) => (
          <div key={bar.label}>
            <div className="mb-2 flex items-end justify-between gap-4">
              <span className="text-xs text-[#91a0a8]">{bar.label}</span>
              <span className="font-mono text-sm text-[#dce5e9]">{valueLabel(bar.value, decimals)}</span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-white/[.055]" role="img" aria-label={`${bar.label}: ${valueLabel(bar.value, decimals)}`}>
              <div className={`h-full rounded-full ${bar.color}`} style={{ width: bar.width }} />
            </div>
          </div>
        ))}
      </div>

      <p className={`mt-6 border-t border-white/[.06] pt-4 text-xs ${adaptiveWorse ? "text-[#d9bd7b]" : "text-[#8fcfab]"}`}>
        {differenceLabel(metric, decimals)}
      </p>
    </article>
  );
}

function LoadingState() {
  return (
    <section className="mt-7 rounded-[24px] border border-white/[.07] bg-[#10171c] p-8" aria-live="polite">
      <p className="font-mono text-xs text-[#72e9a6]">Loading validated benchmark…</p>
    </section>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <section className="mt-7 rounded-[24px] border border-[#ff6670]/25 bg-[#ff6670]/[.06] p-8" role="alert">
      <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#ff8e96]">Benchmark unavailable</p>
      <h2 className="mt-2 text-xl font-medium">Validated analytics could not be loaded</h2>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-[#b9a2a6]">{message}</p>
      <p className="mt-3 text-xs text-[#806f73]">No fallback or demonstration metrics are displayed.</p>
    </section>
  );
}

export default function AnalyticsPage() {
  const [benchmark, setBenchmark] = useState<BenchmarkSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(BENCHMARK_URL, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Benchmark snapshot request failed (${response.status})`);
        const candidate: unknown = await response.json();
        if (!isBenchmarkSnapshot(candidate)) throw new Error("Benchmark snapshot has an invalid or unsupported schema");
        if (!candidate.validation.passed || !candidate.validation.fixed.passed || !candidate.validation.adaptive.passed) {
          throw new Error("Benchmark snapshot did not pass strict completion validation");
        }
        setBenchmark(candidate);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unknown benchmark error");
      });
    return () => controller.abort();
  }, []);

  const waitingDifference = benchmark
    ? benchmark.metrics.total_waiting_time_s.adaptive - benchmark.metrics.total_waiting_time_s.fixed
    : null;

  return (
    <main className="min-h-screen bg-[#080c0f] px-4 py-5 text-[#e8eef4] sm:px-6">
      <div className="mx-auto max-w-[1450px]">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Flowgency</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">Fixed vs Adaptive Analytics</h1>
          </div>
          <SiteNav active="analytics" />
        </header>

        {!benchmark && !error && <LoadingState />}
        {error && <ErrorState message={error} />}

        {benchmark && (
          <>
            <section className="mt-7 overflow-hidden rounded-[26px] border border-white/[.07] bg-[#10171c]">
              <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1.35fr)_minmax(300px,.65fr)]">
                <div>
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full border border-[#72e9a6]/20 bg-[#72e9a6]/[.08] px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-[#72e9a6]">Validated paired run</span>
                    <span className="rounded-full border border-white/10 bg-white/[.035] px-2.5 py-1 font-mono text-[10px] text-[#93a2aa]">Seed {benchmark.provenance.seed}</span>
                  </div>
                  <p className="mt-5 font-mono text-[10px] uppercase tracking-[.2em] text-[#657680]">Scenario</p>
                  <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">{benchmark.scenario_name}</h2>
                  <p className="mt-4 max-w-3xl text-sm leading-6 text-[#8c9ca4]">{benchmark.experiment.controlled_difference}</p>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-[#c7a968]">{benchmark.experiment.adaptive_scope}</p>
                </div>

                <div className="rounded-2xl border border-[#f0bc55]/15 bg-[#f0bc55]/[.055] p-5">
                  <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#d7b664]">Measured outcome</p>
                  <p className="mt-3 text-2xl font-medium text-[#f0dba9]">Adaptive waiting was {Math.abs(benchmark.metrics.total_waiting_time_s.percentage_improvement).toFixed(2)}% {waitingDifference !== null && waitingDifference > 0 ? "higher" : "lower"}</p>
                  <p className="mt-3 text-sm leading-6 text-[#ad9d7a]">J3 adaptive control {waitingDifference !== null && waitingDifference > 0 ? "added" : "removed"} {wholeNumber.format(Math.abs(waitingDifference ?? 0))} vehicle-seconds of waiting in this scenario. This is reported neutrally, without hiding a regression.</p>
                </div>
              </div>
            </section>

            <section className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "Fixed total waiting", value: `${wholeNumber.format(benchmark.metrics.total_waiting_time_s.fixed)} s`, note: `${(benchmark.metrics.total_waiting_time_s.fixed / 3600).toFixed(2)} accumulated hours` },
                { label: "Adaptive total waiting", value: `${wholeNumber.format(benchmark.metrics.total_waiting_time_s.adaptive)} s`, note: `${(benchmark.metrics.total_waiting_time_s.adaptive / 3600).toFixed(2)} accumulated hours` },
                { label: "Arrived vehicles", value: `${benchmark.validation.fixed.arrived} / ${benchmark.validation.adaptive.arrived}`, note: "Fixed / Adaptive · all completed" },
                {
                  label: "Run integrity",
                  value: `${benchmark.validation.fixed.collisions + benchmark.validation.adaptive.collisions} / ${benchmark.validation.fixed.teleports + benchmark.validation.adaptive.teleports}`,
                  note: "Total collisions / teleports across both runs",
                },
              ].map((item) => (
                <article key={item.label} className="rounded-2xl border border-white/[.07] bg-[#10171c] p-5">
                  <p className="text-xs text-[#788892]">{item.label}</p>
                  <p className="mt-5 font-mono text-2xl text-[#dce5e9]">{item.value}</p>
                  <p className="mt-2 text-[10px] uppercase tracking-wider text-[#5f707a]">{item.note}</p>
                </article>
              ))}
            </section>

            <section className="mt-4 grid gap-4 lg:grid-cols-2">
              <ComparisonChart title="Total waiting time" description="Sum of waiting seconds across all 528 completed vehicles" metric={benchmark.metrics.total_waiting_time_s} />
              <ComparisonChart title="Average waiting time" description="Mean waiting time per completed vehicle" metric={benchmark.metrics.average_waiting_time_s} decimals={3} />
              <ComparisonChart title="Total time loss" description="SUMO time loss accumulated across all completed trips" metric={benchmark.metrics.total_time_loss_s} decimals={3} />
              <ComparisonChart title="Average trip duration" description="Mean duration across the identical completed vehicle set" metric={benchmark.metrics.average_trip_duration_s} decimals={3} />
            </section>

            <section className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,.9fr)]">
              <article className="rounded-[22px] border border-white/[.07] bg-[#10171c] p-5 sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#667781]">Validation</p>
                    <h2 className="mt-1 text-base font-medium">Comparable completed runs</h2>
                  </div>
                  <span className="rounded-full border border-[#72e9a6]/20 bg-[#72e9a6]/10 px-2.5 py-1 text-[10px] uppercase tracking-wider text-[#72e9a6]">Passed</span>
                </div>
                <div className="mt-5 overflow-x-auto">
                  <table className="w-full min-w-[520px] text-left text-xs">
                    <thead className="text-[#657680]"><tr><th className="pb-3 font-normal">Run</th><th className="pb-3 font-normal">Departed</th><th className="pb-3 font-normal">Arrived</th><th className="pb-3 font-normal">Unfinished</th><th className="pb-3 font-normal">Collisions</th><th className="pb-3 font-normal">Teleports</th></tr></thead>
                    <tbody className="font-mono text-[#c5d0d6]">
                      {(["fixed", "adaptive"] as const).map((mode) => {
                        const run = benchmark.validation[mode];
                        return <tr key={mode} className="border-t border-white/[.06]"><td className="py-3 capitalize">{mode === "adaptive" ? "Adaptive J3" : "Fixed"}</td><td className="py-3">{run.departed}</td><td className="py-3">{run.arrived}</td><td className="py-3">{run.unfinished}</td><td className="py-3">{run.collisions}</td><td className="py-3">{run.teleports}</td></tr>;
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="mt-4 text-xs leading-5 text-[#71818a]">All {benchmark.validation.matched_vehicle_count} completed vehicle IDs matched exactly. Adaptive made {benchmark.runs.adaptive.cycle_decisions} J3 cycle decisions.</p>
              </article>

              <article className="rounded-[22px] border border-dashed border-white/10 bg-[#0d1317] p-5 sm:p-6">
                <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#667781]">Queue evolution</p>
                <h2 className="mt-2 text-base font-medium">Timeline unavailable</h2>
                <p className="mt-3 text-sm leading-6 text-[#788892]">The validated benchmark retained aggregate trip metrics, but not queue samples over time. No queue curve is inferred or fabricated.</p>
              </article>
            </section>

            <section className="mt-4 rounded-[22px] border border-white/[.07] bg-[#10171c] p-5 sm:p-6">
              <p className="font-mono text-[10px] uppercase tracking-[.18em] text-[#667781]">Limitations and provenance</p>
              <div className="mt-4 grid gap-5 lg:grid-cols-2">
                <ul className="space-y-2 text-sm leading-6 text-[#81919a]">
                  {benchmark.limitations.map((limitation) => <li key={limitation} className="flex gap-3"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#f0bc55]" />{limitation}</li>)}
                </ul>
                <div className="rounded-xl border border-white/[.06] bg-white/[.025] p-4 text-xs leading-6 text-[#71818a]">
                  <p><span className="text-[#9cabb3]">Source:</span> tracked sanitized snapshot of the validated report</p>
                  <p><span className="text-[#9cabb3]">Authoritative report:</span> {benchmark.provenance.authoritative_report}</p>
                  <p><span className="text-[#9cabb3]">Scenario config:</span> {benchmark.provenance.config}</p>
                  <p><span className="text-[#9cabb3]">Snapshot:</span> schema {benchmark.snapshot_schema_version} · {benchmark.provenance.snapshot_created_on}</p>
                </div>
              </div>
            </section>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#72e9a6]/15 bg-[#72e9a6]/[.05] px-5 py-4">
              <p className="text-sm text-[#9babae]">Inspect live SUMO state separately; this page presents a completed offline benchmark.</p>
              <Link href="/simulation" className="text-sm font-medium text-[#72e9a6]">Open Simulation Lab →</Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
