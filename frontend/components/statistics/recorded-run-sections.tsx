/** Sections for a run recorded from Live Simulation (DATA_CONTRACTS.md O.5). */

import type { ControllerMode, NetworkId, RecordedRun, RecordedRunPair, RecordedRunSample, RecordedRunSummary, TrafficProfile } from "@/lib/contracts";
import { LineChart, type LineSeries } from "./charts";
import { formatClock, formatNumber, formatSignedNumber, UNKNOWN } from "./format";
import { DataTable, InlineNote, KpiTile, Num, Pill, StatisticsSection, type PillTone } from "./section";

// Display names as served by GET /api/simulation/configuration-options.
const MODE_LABELS: Record<ControllerMode, string> = {
  fixed_timing: "Fixed Timing",
  adaptive_network: "Adaptive Network",
  adaptive_emergency_priority: "Adaptive Network + Emergency Priority",
};
const NETWORK_LABELS: Record<NetworkId, string> = { single_intersection: "Single Intersection", london: "London Network" };
const PROFILE_LABELS: Record<TrafficProfile, string> = { normal: "Normal", rush_hour: "Rush Hour", unbalanced: "Unbalanced" };

const STATUS_LABELS = { finished: "Finished", stopped: "Stopped", error: "Error" } as const;
const STATUS_TONES: Record<keyof typeof STATUS_LABELS, PillTone> = { finished: "good", stopped: "warn", error: "bad" };

type SummaryKey = "average_waiting_time_s" | "total_waiting_time_s" | "departed_vehicle_count"
  | "arrived_vehicle_count" | "maximum_network_queue_vehicles" | "average_time_loss_s";

/** `better` says how to colour a difference (adaptive − fixed); counts of vehicles are neutral. */
const KPIS: Array<{ key: SummaryKey; label: string; unit: string; digits: number; better: "lower" | null; hint: string }> = [
  { key: "average_waiting_time_s", label: "Average waiting time", unit: "s", digits: 2, better: "lower", hint: "per vehicle" },
  { key: "average_time_loss_s", label: "Average time loss", unit: "s", digits: 2, better: "lower", hint: "per vehicle vs free flow" },
  { key: "maximum_network_queue_vehicles", label: "Max network queue", unit: "veh", digits: 0, better: "lower", hint: "halting vehicles, peak" },
  { key: "total_waiting_time_s", label: "Total waiting time", unit: "s", digits: 0, better: "lower", hint: "all vehicles" },
  { key: "departed_vehicle_count", label: "Departed vehicles", unit: "veh", digits: 0, better: null, hint: "entered the network" },
  { key: "arrived_vehicle_count", label: "Arrived vehicles", unit: "veh", digits: 0, better: null, hint: "completed their trip" },
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
    <InlineNote role="status">
      {run.run.status === "error" ? `The run ended with an error${run.run.error ? `: ${run.run.error}` : ""}. ` : "The run was stopped before all vehicles finished. "}
      Values cover only the simulated part.
    </InlineNote>
  );
}

export function RunInfoSection({ run }: { run: RecordedRun }) {
  const info = run.run;
  return (
    <StatisticsSection
      id="run-info"
      title="Last simulation"
      description="Recorded from Live Simulation. Queues are SUMO state (sumo_halting_number), not camera observations."
      aside={<Pill tone={STATUS_TONES[info.status]}>{STATUS_LABELS[info.status]}</Pill>}
    >
      <div className="grid gap-x-10 gap-y-4 lg:grid-cols-2">
        <dl className="stats-dl">
          <dt>Network</dt><dd>{NETWORK_LABELS[info.network]}</dd>
          <dt>Traffic profile</dt><dd>{PROFILE_LABELS[info.traffic_profile]}</dd>
          <dt>Controller mode</dt><dd>{modeLabel(info.controller_mode)}</dd>
          <dt>Emergency vehicles</dt><dd>{info.emergency_vehicles_enabled ? "Enabled" : "Disabled"}</dd>
        </dl>
        <dl className="stats-dl">
          <dt>Run scenario id</dt><dd className="stats-mono">{info.scenario_id}</dd>
          <dt>Simulated duration</dt><dd>{formatDuration(info.sim_duration_s)}</dd>
          <dt>Ended at</dt><dd>{formatTimestamp(info.ended_at)}</dd>
          <dt>Samples</dt><dd>{info.sample_count} (every {formatNumber(run.timeseries.interval_s, 0)} s of simulation time)</dd>
        </dl>
      </div>
      {run.run.status !== "finished" && <div className="mt-4"><PartialRunNote run={run} /></div>}
    </StatisticsSection>
  );
}

export function RunKpiRow({ run }: { run: RecordedRun }) {
  return (
    <section aria-label="Key indicators">
      <h2 className="sr-only">Key indicators</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {KPIS.map(({ key, label, unit, digits, hint }, index) => (
          <KpiTile
            key={key}
            label={label}
            value={formatNumber(summaryValue(run.summary, key), digits)}
            unit={unit}
            emphasis={index === 0}
            foot={<span>{hint}{run.summary === null ? " · summary not recorded" : ""}</span>}
          />
        ))}
      </div>
    </section>
  );
}

export function RunTimeseriesSection({ run }: { run: RecordedRun }) {
  const { samples } = run.timeseries;
  return (
    <StatisticsSection id="run-timeseries" title="Over time" description={`Sampled every ${formatNumber(run.timeseries.interval_s, 0)} s of simulation time; gaps are unknown values.`}>
      {samples.length === 0 ? <p className="stats-chart-empty">The run was shorter than one sample.</p> : (
        <div className="stats-grid-charts">
          <LineChart title="Network queue" xLabel="simulation time" yLabel="vehicles" formatX={formatClock} formatY={(y) => formatNumber(y, 0)}
            series={[series(samples, "Network queue", (sample) => sample.network_queue_vehicles)]} />
          <LineChart title="Active vehicles" xLabel="simulation time" yLabel="vehicles" formatX={formatClock} formatY={(y) => formatNumber(y, 0)}
            series={[series(samples, "Active vehicles", (sample) => sample.active_vehicle_count)]} />
          <LineChart title="Cumulative departed and arrived" xLabel="simulation time" yLabel="vehicles" formatX={formatClock} formatY={(y) => formatNumber(y, 0)}
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
    <StatisticsSection id="run-intersections" title="Queues per intersection" description="Halting vehicles on each traffic light's controlled lanes, over the samples." aside={<Pill>{run.intersections.length} traffic lights</Pill>}>
      {run.intersections.length === 0 ? <p className="text-sm text-[#dccdc0]">No intersection samples were recorded.</p> : (
        <DataTable caption="Queues per intersection">
          <thead><tr><th>Traffic light</th><th>Mean queue (veh)</th><th>Max queue (veh)</th><th>Samples</th></tr></thead>
          <tbody>
            {run.intersections.map((item) => (
              <tr key={item.traffic_light_id}>
                <td className="stats-mono">{item.traffic_light_id}</td>
                <Num>{formatNumber(item.mean_queue_vehicles, 2)}</Num>
                <Num>{formatNumber(item.max_queue_vehicles, 0)}</Num>
                <td>{item.sample_count}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </StatisticsSection>
  );
}

export function RunPhasesSection({ run }: { run: RecordedRun }) {
  return (
    <StatisticsSection id="run-phases" title="Signal phases" description="Observed at every simulation step. Mean green averages completed phases containing G/g and no y/Y; the phase still running at the end is excluded.">
      {run.phases.length === 0 ? <p className="text-sm text-[#dccdc0]">No traffic light phases were observed.</p> : (
        <DataTable caption="Signal phases per traffic light">
          <thead><tr><th>Traffic light</th><th>Phase changes</th><th>Completed green phases</th><th>Mean green (s)</th></tr></thead>
          <tbody>
            {run.phases.map((item) => (
              <tr key={item.traffic_light_id}>
                <td className="stats-mono">{item.traffic_light_id}</td>
                <td>{item.phase_change_count}</td>
                <td>{item.completed_green_phases}</td>
                <Num>{formatNumber(item.mean_green_duration_s, 1)}</Num>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </StatisticsSection>
  );
}

function difference(fixed: number | null, adaptive: number | null) {
  return fixed === null || adaptive === null ? null : adaptive - fixed;
}

function DifferenceCell({ value, digits, better }: { value: number | null; digits: number; better: "lower" | null }) {
  const text = formatSignedNumber(value, digits);
  const tone = value === null || value === 0 || better === null ? undefined : (value < 0) === (better === "lower") ? "good" : "bad";
  return <td className={value === null ? "stats-unknown" : undefined}><span className="stats-delta" data-tone={tone}>{text}</span></td>;
}

export function RunComparisonSection({ fixed, adaptive }: { fixed: RecordedRun; adaptive: RecordedRun }) {
  const fixedLabel = modeLabel(fixed.run.controller_mode);
  const adaptiveLabel = modeLabel(adaptive.run.controller_mode);
  const partial = fixed.run.status !== "finished" || adaptive.run.status !== "finished";
  const overlay = (title: string, pick: (sample: RecordedRunSample) => number | null) => (
    <LineChart title={title} xLabel="simulation time" yLabel="vehicles" formatX={formatClock} formatY={(y) => formatNumber(y, 0)}
      series={[series(fixed.timeseries.samples, fixedLabel, pick), series(adaptive.timeseries.samples, adaptiveLabel, pick)]} />
  );
  return (
    <StatisticsSection
      id="run-comparison"
      title="Fixed vs adaptive"
      description="Latest recorded run of each mode for this scenario. Difference is adaptive − fixed; green means adaptive did better. Live runs are not matched trip by trip."
      aside={<Pill tone="accent">{fixed.run.scenario_id}</Pill>}
    >
      {partial && <div className="mb-4"><InlineNote role="status">At least one of these runs did not finish, so the comparison covers different simulated periods.</InlineNote></div>}
      <DataTable caption="Fixed vs adaptive comparison">
        <thead><tr><th>Metric</th><th>{fixedLabel}</th><th>{adaptiveLabel}</th><th>Difference</th></tr></thead>
        <tbody>
          <tr>
            <td>Status / ended at</td>
            <td className="stats-text">{STATUS_LABELS[fixed.run.status]}, {formatTimestamp(fixed.run.ended_at)}</td>
            <td className="stats-text">{STATUS_LABELS[adaptive.run.status]}, {formatTimestamp(adaptive.run.ended_at)}</td>
            <td className="stats-unknown">{UNKNOWN}</td>
          </tr>
          <tr>
            <td>Simulated duration (s)</td>
            <Num>{formatNumber(fixed.run.sim_duration_s, 0)}</Num>
            <Num>{formatNumber(adaptive.run.sim_duration_s, 0)}</Num>
            <DifferenceCell value={difference(fixed.run.sim_duration_s, adaptive.run.sim_duration_s)} digits={0} better={null} />
          </tr>
          {KPIS.map(({ key, label, unit, digits, better }) => {
            const a = summaryValue(fixed.summary, key);
            const b = summaryValue(adaptive.summary, key);
            return (
              <tr key={key}>
                <td>{label} ({unit})</td>
                <Num>{formatNumber(a, digits)}</Num>
                <Num>{formatNumber(b, digits)}</Num>
                <DifferenceCell value={difference(a, b)} digits={digits} better={better} />
              </tr>
            );
          })}
        </tbody>
      </DataTable>
      <div className="stats-grid-charts mt-6">
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
