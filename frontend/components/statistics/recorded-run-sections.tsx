/** Sections for a run recorded from Live Simulation (DATA_CONTRACTS.md O.5). Skeleton styling. */

import type { ControllerMode, NetworkId, RecordedRun, RecordedRunPair, RecordedRunSample, RecordedRunSummary, TrafficProfile } from "@/lib/contracts";
import { LineChart, type LineSeries } from "./charts";
import { formatClock, formatNumber, formatSignedNumber, formatWithUnit, UNKNOWN } from "./format";
import { StatisticsSection, tableClass } from "./section";

// Display names as served by GET /api/simulation/configuration-options.
const MODE_LABELS: Record<ControllerMode, string> = {
  fixed_timing: "Fixed Timing",
  adaptive_network: "Adaptive Network",
  adaptive_emergency_priority: "Adaptive Network + Emergency Priority",
};
const NETWORK_LABELS: Record<NetworkId, string> = { single_intersection: "Single Intersection", london: "London Network" };
const PROFILE_LABELS: Record<TrafficProfile, string> = { normal: "Normal", rush_hour: "Rush Hour", unbalanced: "Unbalanced" };

const STATUS_LABELS = { finished: "Finished", stopped: "Stopped", error: "Error" } as const;

type SummaryKey = "average_waiting_time_s" | "total_waiting_time_s" | "departed_vehicle_count"
  | "arrived_vehicle_count" | "maximum_network_queue_vehicles" | "average_time_loss_s";

const KPIS: Array<{ key: SummaryKey; label: string; unit: string; digits: number }> = [
  { key: "average_waiting_time_s", label: "Average waiting time", unit: "s", digits: 2 },
  { key: "total_waiting_time_s", label: "Total waiting time", unit: "s", digits: 0 },
  { key: "departed_vehicle_count", label: "Departed vehicles", unit: "veh", digits: 0 },
  { key: "arrived_vehicle_count", label: "Arrived vehicles", unit: "veh", digits: 0 },
  { key: "maximum_network_queue_vehicles", label: "Max network queue", unit: "veh", digits: 0 },
  { key: "average_time_loss_s", label: "Average time loss", unit: "s", digits: 2 },
];

export function modeLabel(mode: ControllerMode) {
  return MODE_LABELS[mode];
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-GB");
}

function formatDuration(seconds: number | null) {
  return seconds === null ? UNKNOWN : `${formatClock(seconds)} (${formatNumber(seconds, 0)} s)`;
}

function summaryValue(summary: RecordedRunSummary | null, key: SummaryKey) {
  return summary ? summary[key] : null;
}

function series(samples: RecordedRunSample[], label: string, pick: (sample: RecordedRunSample) => number | null): LineSeries {
  return {
    label,
    points: samples.flatMap((sample) => (sample.t_s === null ? [] : [{ x: sample.t_s, y: pick(sample) }])),
  };
}

function PartialRunNote({ run }: { run: RecordedRun }) {
  if (run.run.status === "finished") return null;
  return (
    <p role="status" className="mt-2 text-sm">
      {run.run.status === "error" ? `The run ended with an error${run.run.error ? `: ${run.run.error}` : ""}. ` : "The run was stopped before all vehicles finished. "}
      Values cover only the simulated part.
    </p>
  );
}

export function RunInfoSection({ run }: { run: RecordedRun }) {
  const info = run.run;
  return (
    <StatisticsSection id="run-info" title="Last simulation" description="Recorded from Live Simulation. Queues are SUMO state (sumo_halting_number), not camera observations.">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        <dt>Network</dt><dd>{NETWORK_LABELS[info.network]}</dd>
        <dt>Traffic profile</dt><dd>{PROFILE_LABELS[info.traffic_profile]}</dd>
        <dt>Controller mode</dt><dd>{modeLabel(info.controller_mode)}</dd>
        <dt>Emergency vehicles</dt><dd>{info.emergency_vehicles_enabled ? "Enabled" : "Disabled"}</dd>
        <dt>Run scenario id</dt><dd>{info.scenario_id}</dd>
        <dt>Status</dt><dd>{STATUS_LABELS[info.status]}</dd>
        <dt>Simulated duration</dt><dd>{formatDuration(info.sim_duration_s)}</dd>
        <dt>Ended at</dt><dd>{formatTimestamp(info.ended_at)}</dd>
        <dt>Samples</dt><dd>{info.sample_count} (every {formatNumber(run.timeseries.interval_s, 0)} s of simulation time)</dd>
      </dl>
      <PartialRunNote run={run} />
    </StatisticsSection>
  );
}

export function RunKpiRow({ run }: { run: RecordedRun }) {
  return (
    <section aria-label="Key indicators" className="statistics-kpis mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {KPIS.map(({ key, label, unit, digits }) => (
        <article key={key} className="statistics-kpi rounded-xl border border-white/10 p-3">
          <h3 className="text-xs opacity-70">{label}</h3>
          <p className="mt-1 text-lg">{formatWithUnit(summaryValue(run.summary, key), unit, digits)}</p>
        </article>
      ))}
    </section>
  );
}

export function RunTimeseriesSection({ run }: { run: RecordedRun }) {
  const { samples } = run.timeseries;
  return (
    <StatisticsSection id="run-timeseries" title="Over time" description={`Sampled every ${formatNumber(run.timeseries.interval_s, 0)} s of simulation time; gaps are unknown values.`}>
      {samples.length === 0 ? <p className="text-sm">The run was shorter than one sample.</p> : (
        <div className="grid gap-6 lg:grid-cols-2">
          <LineChart title="Network queue" xLabel="simulation time" yLabel="vehicles" formatX={formatClock}
            series={[series(samples, "Network queue", (sample) => sample.network_queue_vehicles)]} />
          <LineChart title="Active vehicles" xLabel="simulation time" yLabel="vehicles" formatX={formatClock}
            series={[series(samples, "Active vehicles", (sample) => sample.active_vehicle_count)]} />
          <LineChart title="Cumulative departed and arrived" xLabel="simulation time" yLabel="vehicles" formatX={formatClock}
            series={[
              series(samples, "Departed", (sample) => sample.departed_cumulative),
              series(samples, "Arrived", (sample) => sample.arrived_cumulative),
            ]} />
        </div>
      )}
    </StatisticsSection>
  );
}

export function RunIntersectionsSection({ run }: { run: RecordedRun }) {
  return (
    <StatisticsSection id="run-intersections" title="Queues per intersection" description="Halting vehicles on each traffic light's controlled lanes, over the samples.">
      {run.intersections.length === 0 ? <p className="text-sm">No intersection samples were recorded.</p> : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr><th>Traffic light</th><th>Mean queue (veh)</th><th>Max queue (veh)</th><th>Samples</th></tr></thead>
            <tbody>
              {run.intersections.map((item) => (
                <tr key={item.traffic_light_id}>
                  <td>{item.traffic_light_id}</td>
                  <td>{formatNumber(item.mean_queue_vehicles, 2)}</td>
                  <td>{formatNumber(item.max_queue_vehicles, 0)}</td>
                  <td>{item.sample_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </StatisticsSection>
  );
}

export function RunPhasesSection({ run }: { run: RecordedRun }) {
  return (
    <StatisticsSection id="run-phases" title="Signal phases" description="Observed at every simulation step. Mean green averages completed phases containing G/g and no y/Y; the phase still running at the end is excluded.">
      {run.phases.length === 0 ? <p className="text-sm">No traffic light phases were observed.</p> : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead><tr><th>Traffic light</th><th>Phase changes</th><th>Completed green phases</th><th>Mean green (s)</th></tr></thead>
            <tbody>
              {run.phases.map((item) => (
                <tr key={item.traffic_light_id}>
                  <td>{item.traffic_light_id}</td>
                  <td>{item.phase_change_count}</td>
                  <td>{item.completed_green_phases}</td>
                  <td>{formatNumber(item.mean_green_duration_s, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </StatisticsSection>
  );
}

function difference(fixed: number | null, adaptive: number | null) {
  return fixed === null || adaptive === null ? null : adaptive - fixed;
}

export function RunComparisonSection({ fixed, adaptive }: { fixed: RecordedRun; adaptive: RecordedRun }) {
  const fixedLabel = modeLabel(fixed.run.controller_mode);
  const adaptiveLabel = modeLabel(adaptive.run.controller_mode);
  const partial = fixed.run.status !== "finished" || adaptive.run.status !== "finished";
  const overlay = (title: string, pick: (sample: RecordedRunSample) => number | null) => (
    <LineChart title={title} xLabel="simulation time" yLabel="vehicles" formatX={formatClock}
      series={[series(fixed.timeseries.samples, fixedLabel, pick), series(adaptive.timeseries.samples, adaptiveLabel, pick)]} />
  );
  return (
    <StatisticsSection id="run-comparison" title={`Fixed vs adaptive — ${fixed.run.scenario_id}`}
      description="Latest recorded run of each mode for this scenario. Difference is adaptive − fixed. Live runs are not matched trip by trip.">
      {partial && <p role="status" className="mb-3 text-sm">At least one of these runs did not finish, so the comparison covers different simulated periods.</p>}
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead><tr><th>Metric</th><th>{fixedLabel}</th><th>{adaptiveLabel}</th><th>Difference</th></tr></thead>
          <tbody>
            <tr>
              <td>Status / ended at</td>
              <td>{STATUS_LABELS[fixed.run.status]}, {formatTimestamp(fixed.run.ended_at)}</td>
              <td>{STATUS_LABELS[adaptive.run.status]}, {formatTimestamp(adaptive.run.ended_at)}</td>
              <td>{UNKNOWN}</td>
            </tr>
            <tr>
              <td>Simulated duration (s)</td>
              <td>{formatNumber(fixed.run.sim_duration_s, 0)}</td>
              <td>{formatNumber(adaptive.run.sim_duration_s, 0)}</td>
              <td>{formatSignedNumber(difference(fixed.run.sim_duration_s, adaptive.run.sim_duration_s), 0)}</td>
            </tr>
            {KPIS.map(({ key, label, unit, digits }) => {
              const a = summaryValue(fixed.summary, key);
              const b = summaryValue(adaptive.summary, key);
              return (
                <tr key={key}>
                  <td>{label} ({unit})</td>
                  <td>{formatNumber(a, digits)}</td>
                  <td>{formatNumber(b, digits)}</td>
                  <td>{formatSignedNumber(difference(a, b), digits)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {overlay("Network queue", (sample) => sample.network_queue_vehicles)}
        {overlay("Cumulative arrived", (sample) => sample.arrived_cumulative)}
      </div>
    </StatisticsSection>
  );
}

export function RecordedRunStatistics({ run, pair }: { run: RecordedRun; pair: RecordedRunPair | null }) {
  return (
    <>
      <RunInfoSection run={run} />
      <RunKpiRow run={run} />
      <RunTimeseriesSection run={run} />
      <RunIntersectionsSection run={run} />
      <RunPhasesSection run={run} />
      {pair?.fixed && pair.adaptive && <RunComparisonSection fixed={pair.fixed} adaptive={pair.adaptive} />}
    </>
  );
}
