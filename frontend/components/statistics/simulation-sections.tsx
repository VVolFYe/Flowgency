/** One component per section of a simulation (fixed vs adaptive) analytics file. */

import {
  COMPARISON_MODES,
  SIMULATION_DISTRIBUTION_KEYS,
  SIMULATION_SUMMARY_KEYS,
  type ComparisonMode,
  type PairedMetric,
  type SimulationAnalytics,
  type SimulationSummaryKey,
  type TimeseriesSample,
} from "@/lib/contracts";
import { GroupedBarChart, LineChart } from "./charts";
import { formatClock, formatNumber, formatPercent, formatSignedNumber, UNKNOWN } from "./format";
import { LimitationsSection, StatisticsSection, tableClass } from "./section";

const SUMMARY_LABELS: Record<SimulationSummaryKey, { label: string; unit: string }> = {
  total_waiting_time_s: { label: "Total waiting time", unit: "s" },
  average_waiting_time_s: { label: "Average waiting time", unit: "s" },
  total_time_loss_s: { label: "Total time loss", unit: "s" },
  average_time_loss_s: { label: "Average time loss", unit: "s" },
  average_trip_duration_s: { label: "Average trip duration", unit: "s" },
  throughput_vehicles_per_hour: { label: "Throughput", unit: "veh/h" },
  mean_network_queue_vehicles: { label: "Mean network queue", unit: "veh" },
  max_network_queue_vehicles: { label: "Max network queue", unit: "veh" },
};

const DISTRIBUTION_LABELS = {
  waiting_time_s: "Waiting time per trip",
  time_loss_s: "Time loss per trip",
  trip_duration_s: "Trip duration",
} as const;

const KPI_KEYS: SimulationSummaryKey[] = [
  "average_waiting_time_s", "average_time_loss_s", "throughput_vehicles_per_hour", "mean_network_queue_vehicles",
];

function modeLabel(data: SimulationAnalytics, mode: ComparisonMode) {
  return mode === "fixed" ? data.experiment.fixed_label : data.experiment.adaptive_label;
}

export function SimulationHeader({ data }: { data: SimulationAnalytics }) {
  const { provenance, experiment } = data;
  return (
    <header className="statistics-header mt-6">
      <h2 className="text-xl font-semibold">{data.scenario_name}</h2>
      <p className="mt-1 text-sm">{experiment.controlled_difference}</p>
      <p className="mt-1 text-sm">{experiment.adaptive_scope}</p>
      {!data.validation.passed && (
        <p role="status" className="mt-2 text-sm font-medium">Validation failed — values are shown for inspection only, not as a valid comparison.</p>
      )}
      <details className="mt-2 text-xs">
        <summary>Provenance</summary>
        <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
          <dt>Config</dt><dd>{provenance.config ?? UNKNOWN}</dd>
          <dt>Network</dt><dd>{provenance.network ?? UNKNOWN}</dd>
          <dt>Routes</dt><dd>{provenance.routes || UNKNOWN}</dd>
          <dt>Adaptive manifest</dt><dd>{provenance.adaptive_manifest ?? UNKNOWN}</dd>
          <dt>Seed</dt><dd>{provenance.seed ?? UNKNOWN}</dd>
          <dt>Expected vehicles</dt><dd>{provenance.expected_vehicle_count}</dd>
          <dt>Report</dt><dd>{provenance.authoritative_report ?? UNKNOWN}</dd>
          <dt>Created</dt><dd>{provenance.snapshot_created_on}</dd>
        </dl>
      </details>
    </header>
  );
}

function ImprovementNote({ metric }: { metric: PairedMetric }) {
  if (metric.percentage_improvement === null) return <span>Change unknown</span>;
  const better = metric.percentage_improvement > 0;
  const worse = metric.percentage_improvement < 0;
  return <span>{formatPercent(metric.percentage_improvement)} {better ? "(adaptive better)" : worse ? "(adaptive worse)" : "(no change)"}</span>;
}

export function KpiRow({ data }: { data: SimulationAnalytics }) {
  return (
    <section aria-label="Key indicators" className="statistics-kpis mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {KPI_KEYS.map((key) => {
        const metric = data.summary[key];
        const { label, unit } = SUMMARY_LABELS[key];
        return (
          <article key={key} className="statistics-kpi rounded-xl border border-white/10 p-3">
            <h3 className="text-xs opacity-70">{label} ({unit})</h3>
            <p className="mt-1 text-sm">{data.experiment.fixed_label}: {formatNumber(metric.fixed, 2)}</p>
            <p className="text-sm">{data.experiment.adaptive_label}: {formatNumber(metric.adaptive, 2)}</p>
            <p className="mt-1 text-xs"><ImprovementNote metric={metric} /></p>
          </article>
        );
      })}
    </section>
  );
}

export function PairedMetricsTable({ data }: { data: SimulationAnalytics }) {
  return (
    <StatisticsSection id="paired-metrics" title="Paired metrics" description="Positive improvement favours adaptive (lower is better, except throughput).">
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead><tr><th>Metric</th><th>{data.experiment.fixed_label}</th><th>{data.experiment.adaptive_label}</th><th>Improvement</th><th>Improvement %</th><th>Better</th></tr></thead>
          <tbody>
            {SIMULATION_SUMMARY_KEYS.map((key) => {
              const metric = data.summary[key];
              const { label, unit } = SUMMARY_LABELS[key];
              return (
                <tr key={key}>
                  <td>{label} ({unit})</td>
                  <td>{formatNumber(metric.fixed, 3)}</td>
                  <td>{formatNumber(metric.adaptive, 3)}</td>
                  <td>{formatSignedNumber(metric.absolute_improvement, 3)}</td>
                  <td>{formatPercent(metric.percentage_improvement)}</td>
                  <td>{metric.better}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {data.validation.matched_vehicle_count !== null && <p className="mt-2 text-xs">Matched vehicles: {data.validation.matched_vehicle_count}</p>}
    </StatisticsSection>
  );
}

const TIMESERIES_FIELDS: Array<{ key: keyof Omit<TimeseriesSample, "t_s">; title: string; unit: string }> = [
  { key: "network_queue_vehicles", title: "Network queue", unit: "halting vehicles" },
  { key: "active_vehicles", title: "Active vehicles", unit: "vehicles" },
  { key: "arrived_cumulative", title: "Arrived (cumulative)", unit: "vehicles" },
];

export function TimeSeriesSection({ data }: { data: SimulationAnalytics }) {
  const available = COMPARISON_MODES.filter((mode) => data.timeseries[mode] !== null);
  return (
    <StatisticsSection id="timeseries" title="Time series" description={`One sample per ${data.timeseries.interval_s} s of simulation time. Queue: ${data.timeseries.queue_measurement}.`}>
      {available.length === 0 ? <p className="text-sm">No per-step samples in this file.</p> : (
        <div className="grid gap-4 lg:grid-cols-3">
          {TIMESERIES_FIELDS.map((field) => (
            <LineChart
              key={field.key}
              title={field.title}
              xLabel="simulation time"
              yLabel={field.unit}
              formatX={formatClock}
              series={available.map((mode) => ({
                label: modeLabel(data, mode),
                points: (data.timeseries[mode] ?? []).map((row) => ({ x: row.t_s, y: row[field.key] })),
              }))}
            />
          ))}
        </div>
      )}
      {COMPARISON_MODES.filter((mode) => data.timeseries[mode] === null).map((mode) => (
        <p key={mode} className="mt-2 text-xs">{modeLabel(data, mode)}: samples unknown (missing).</p>
      ))}
    </StatisticsSection>
  );
}

export function DistributionsSection({ data }: { data: SimulationAnalytics }) {
  return (
    <StatisticsSection id="distributions" title="Distributions" description="Completed trips. Both modes share the same histogram bins.">
      <div className="grid gap-6 lg:grid-cols-3">
        {SIMULATION_DISTRIBUTION_KEYS.map((key) => {
          const item = data.distributions[key];
          const edges = item.bin_edges;
          const categories = edges ? edges.slice(0, -1).map((edge, index) => `${formatNumber(edge, 1)}–${formatNumber(edges[index + 1], 1)} s`) : [];
          return (
            <article key={key} className="statistics-distribution">
              <h3 className="text-sm font-medium">{DISTRIBUTION_LABELS[key]}</h3>
              <GroupedBarChart
                title={`${DISTRIBUTION_LABELS[key]} histogram`}
                categories={categories}
                yLabel="trips"
                series={COMPARISON_MODES.map((mode) => ({
                  label: modeLabel(data, mode),
                  values: item[mode]?.histogram ?? categories.map(() => null),
                }))}
              />
              <table className={`${tableClass} mt-2`}>
                <thead><tr><th>Mode</th><th>n</th><th>p50</th><th>p90</th><th>p95</th><th>max</th></tr></thead>
                <tbody>
                  {COMPARISON_MODES.map((mode) => {
                    const stats = item[mode];
                    return (
                      <tr key={mode}>
                        <td>{modeLabel(data, mode)}</td>
                        <td>{stats ? stats.count : UNKNOWN}</td>
                        <td>{formatNumber(stats?.p50, 1)}</td>
                        <td>{formatNumber(stats?.p90, 1)}</td>
                        <td>{formatNumber(stats?.p95, 1)}</td>
                        <td>{formatNumber(stats?.max, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </article>
          );
        })}
      </div>
    </StatisticsSection>
  );
}

export function IntersectionsTable({ data }: { data: SimulationAnalytics }) {
  const ids = Array.from(new Set(COMPARISON_MODES.flatMap((mode) => Object.keys(data.intersections[mode] ?? {})))).sort();
  return (
    <StatisticsSection id="intersections" title="Intersections" description={`Per traffic-light controller. Queue: ${data.intersections.queue_measurement}.`}>
      {ids.length === 0 ? <p className="text-sm">No per-controller samples in this file.</p> : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <thead>
              <tr><th rowSpan={2}>Traffic light</th>{COMPARISON_MODES.map((mode) => <th key={mode} colSpan={4}>{modeLabel(data, mode)}</th>)}</tr>
              <tr>{COMPARISON_MODES.map((mode) => ["Mean queue", "Max queue", "Mean green (s)", "Decisions"].map((label) => <th key={`${mode}-${label}`}>{label}</th>))}</tr>
            </thead>
            <tbody>
              {ids.map((id) => (
                <tr key={id}>
                  <td>{id}</td>
                  {COMPARISON_MODES.map((mode) => {
                    const stats = data.intersections[mode]?.[id];
                    return [
                      <td key={`${mode}-mean`}>{formatNumber(stats?.mean_queue, 2)}</td>,
                      <td key={`${mode}-max`}>{formatNumber(stats?.max_queue, 0)}</td>,
                      <td key={`${mode}-green`}>{formatNumber(stats?.mean_green_s, 1)}</td>,
                      <td key={`${mode}-decisions`}>{formatNumber(stats?.decision_count, 0)}</td>,
                    ];
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </StatisticsSection>
  );
}

export function EmergencySection({ data }: { data: SimulationAnalytics }) {
  const emergency = data.emergency;
  return (
    <StatisticsSection id="emergency" title="Emergency vehicles">
      {emergency === null ? <p className="text-sm">This scenario has no emergency-vehicle trips.</p> : (
        <table className={tableClass}>
          <thead><tr><th>Mode</th><th>Emergency trips</th><th>Emergency avg time loss (s)</th><th>Normal trips</th><th>Normal avg time loss (s)</th></tr></thead>
          <tbody>
            {COMPARISON_MODES.map((mode) => {
              const stats = emergency[mode];
              return (
                <tr key={mode}>
                  <td>{modeLabel(data, mode)}</td>
                  <td>{stats ? stats.emergency_trip_count : UNKNOWN}</td>
                  <td>{formatNumber(stats?.emergency_average_time_loss_s, 2)}</td>
                  <td>{stats ? stats.normal_trip_count : UNKNOWN}</td>
                  <td>{formatNumber(stats?.normal_average_time_loss_s, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {emergency && <p className="mt-2 text-xs">Emergency vehicle types: {emergency.vehicle_types.join(", ")}</p>}
    </StatisticsSection>
  );
}

const VALIDATION_FIELDS = [
  ["departed", "Departed"], ["arrived", "Arrived"], ["completed", "Completed"], ["unfinished", "Unfinished"],
  ["duplicate_tripinfo_ids", "Duplicate tripinfo IDs"], ["collisions", "Collisions"], ["teleports", "Teleports"],
  ["process_exit_code", "Exit code"],
] as const;

export function ValidationSection({ data }: { data: SimulationAnalytics }) {
  const { validation } = data;
  return (
    <StatisticsSection id="validation" title="Validation">
      <p className="text-sm font-medium">{validation.passed ? "Passed" : "Failed"}</p>
      <table className={`${tableClass} mt-2`}>
        <thead><tr><th>Check</th>{COMPARISON_MODES.map((mode) => <th key={mode}>{modeLabel(data, mode)}</th>)}</tr></thead>
        <tbody>
          <tr><td>Passed</td>{COMPARISON_MODES.map((mode) => <td key={mode}>{validation[mode].passed ? "yes" : "no"}</td>)}</tr>
          {VALIDATION_FIELDS.map(([key, label]) => (
            <tr key={key}><td>{label}</td>{COMPARISON_MODES.map((mode) => <td key={mode}>{formatNumber(validation[mode][key], 0)}</td>)}</tr>
          ))}
          <tr><td>Stopped by step limit</td>{COMPARISON_MODES.map((mode) => {
            const value = validation[mode].terminated_by_step_limit;
            return <td key={mode}>{value === null ? UNKNOWN : value ? "yes" : "no"}</td>;
          })}</tr>
        </tbody>
      </table>
      {validation.errors.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-sm">{validation.errors.map((error) => <li key={error}>{error}</li>)}</ul>
      )}
    </StatisticsSection>
  );
}

export function SimulationStatistics({ data }: { data: SimulationAnalytics }) {
  return (
    <>
      <SimulationHeader data={data} />
      <KpiRow data={data} />
      <PairedMetricsTable data={data} />
      <TimeSeriesSection data={data} />
      <DistributionsSection data={data} />
      <IntersectionsTable data={data} />
      <EmergencySection data={data} />
      <ValidationSection data={data} />
      <LimitationsSection limitations={data.limitations} />
    </>
  );
}
