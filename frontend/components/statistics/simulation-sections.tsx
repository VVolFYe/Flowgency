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
import { DataTable, InlineNote, KpiTile, LimitationsSection, Num, Pill, StatisticsSection, type PillTone } from "./section";

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

/** Tone for a percentage improvement as computed by the exporter (positive favours adaptive). */
function improvementTone(metric: PairedMetric): PillTone {
  if (metric.percentage_improvement === null) return "neutral";
  if (metric.percentage_improvement > 0) return "good";
  if (metric.percentage_improvement < 0) return "bad";
  return "neutral";
}

export function SimulationHeader({ data }: { data: SimulationAnalytics }) {
  const { provenance, experiment } = data;
  return (
    <section aria-labelledby="simulation-title" className="stats-card">
      <div className="stats-card-body">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="stats-group-title">Simulation · SUMO fixed vs adaptive</p>
            <h2 id="simulation-title" className="mt-2 text-xl font-bold tracking-[-.02em] text-[#fff4eb] sm:text-2xl">{data.scenario_name}</h2>
          </div>
          <Pill tone={data.validation.passed ? "good" : "bad"}>{data.validation.passed ? "Validation passed" : "Validation failed"}</Pill>
        </div>
        <div className="mt-4 grid gap-3 text-[13px] leading-6 text-[#dccdc0] lg:grid-cols-2">
          <p><span className="font-semibold text-[#fff4eb]">Controlled difference. </span>{experiment.controlled_difference}</p>
          <p><span className="font-semibold text-[#fff4eb]">Adaptive scope. </span>{experiment.adaptive_scope}</p>
        </div>
        {!data.validation.passed && (
          <div className="mt-4"><InlineNote role="status">Validation failed — values are shown for inspection only, not as a valid comparison.</InlineNote></div>
        )}
        <details className="stats-details mt-4">
          <summary>Provenance</summary>
          <dl className="stats-dl mt-3">
            <dt>Config</dt><dd className="stats-mono">{provenance.config ?? UNKNOWN}</dd>
            <dt>Network</dt><dd className="stats-mono">{provenance.network ?? UNKNOWN}</dd>
            <dt>Routes</dt><dd className="stats-mono">{provenance.routes || UNKNOWN}</dd>
            <dt>Adaptive manifest</dt><dd className="stats-mono">{provenance.adaptive_manifest ?? UNKNOWN}</dd>
            <dt>Seed</dt><dd>{provenance.seed ?? UNKNOWN}</dd>
            <dt>Expected vehicles</dt><dd>{provenance.expected_vehicle_count}</dd>
            <dt>Report</dt><dd className="stats-mono">{provenance.authoritative_report ?? UNKNOWN}</dd>
            <dt>Created</dt><dd>{provenance.snapshot_created_on}</dd>
          </dl>
        </details>
      </div>
    </section>
  );
}

export function KpiRow({ data }: { data: SimulationAnalytics }) {
  return (
    <section aria-label="Key indicators">
      <h2 className="sr-only">Key indicators</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {KPI_KEYS.map((key, index) => {
          const metric = data.summary[key];
          const { label, unit } = SUMMARY_LABELS[key];
          const tone = improvementTone(metric);
          return (
            <KpiTile
              key={key}
              label={label}
              value={formatNumber(metric.adaptive, 2)}
              unit={unit}
              emphasis={index === 0}
              foot={(
                <>
                  <span><strong>{data.experiment.adaptive_label}</strong> · {data.experiment.fixed_label}: {formatNumber(metric.fixed, 2)}{metric.fixed === null ? "" : ` ${unit}`}</span>
                  {metric.percentage_improvement === null
                    ? <Pill>Change unknown</Pill>
                    : <Pill tone={tone}>{formatPercent(metric.percentage_improvement)}{tone === "good" ? " better" : tone === "bad" ? " worse" : " no change"}</Pill>}
                </>
              )}
            />
          );
        })}
      </div>
    </section>
  );
}

export function PairedMetricsTable({ data }: { data: SimulationAnalytics }) {
  return (
    <StatisticsSection
      id="paired-metrics"
      title="Paired metrics"
      description="Positive improvement favours adaptive (lower is better, except throughput)."
      aside={data.validation.matched_vehicle_count !== null ? <Pill>{data.validation.matched_vehicle_count} matched vehicles</Pill> : undefined}
    >
      <DataTable caption="Paired metrics, fixed vs adaptive">
        <thead><tr><th>Metric</th><th>{data.experiment.fixed_label}</th><th>{data.experiment.adaptive_label}</th><th>Improvement</th><th>Improvement %</th><th>Better</th></tr></thead>
        <tbody>
          {SIMULATION_SUMMARY_KEYS.map((key) => {
            const metric = data.summary[key];
            const { label, unit } = SUMMARY_LABELS[key];
            const tone = improvementTone(metric);
            return (
              <tr key={key}>
                <td>{label} ({unit})</td>
                <Num>{formatNumber(metric.fixed, 3)}</Num>
                <Num>{formatNumber(metric.adaptive, 3)}</Num>
                <td className={metric.absolute_improvement === null ? "stats-unknown" : undefined}><span className="stats-delta" data-tone={tone === "neutral" ? undefined : tone}>{formatSignedNumber(metric.absolute_improvement, 3)}</span></td>
                <td className={metric.percentage_improvement === null ? "stats-unknown" : undefined}><span className="stats-delta" data-tone={tone === "neutral" ? undefined : tone}>{formatPercent(metric.percentage_improvement)}</span></td>
                <td>{metric.better}</td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
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
  const missing = COMPARISON_MODES.filter((mode) => data.timeseries[mode] === null);
  return (
    <StatisticsSection id="timeseries" title="Time series" description={`One sample per ${data.timeseries.interval_s} s of simulation time. Queue: ${data.timeseries.queue_measurement}.`}>
      {available.length === 0 ? <p className="stats-chart-empty">No per-step samples in this file.</p> : (
        <div className="stats-grid-charts">
          {TIMESERIES_FIELDS.map((field) => (
            <LineChart
              key={field.key}
              title={field.title}
              xLabel="simulation time"
              yLabel={field.unit}
              formatX={formatClock}
              formatY={(y) => formatNumber(y, 0)}
              series={available.map((mode) => ({
                label: modeLabel(data, mode),
                points: (data.timeseries[mode] ?? []).map((row) => ({ x: row.t_s, y: row[field.key] })),
              }))}
            />
          ))}
        </div>
      )}
      {missing.length > 0 && (
        <div className="mt-4 flex flex-col gap-2">
          {missing.map((mode) => <InlineNote key={mode}>{modeLabel(data, mode)}: samples unknown (missing).</InlineNote>)}
        </div>
      )}
    </StatisticsSection>
  );
}

export function DistributionsSection({ data }: { data: SimulationAnalytics }) {
  return (
    <StatisticsSection id="distributions" title="Distributions" description="Completed trips. Both modes share the same histogram bins.">
      <div className="stats-grid-charts">
        {SIMULATION_DISTRIBUTION_KEYS.map((key) => {
          const item = data.distributions[key];
          const edges = item.bin_edges;
          const categories = edges ? edges.slice(0, -1).map((edge, index) => `${formatNumber(edge, 1)}–${formatNumber(edges[index + 1], 1)} s`) : [];
          return (
            <article key={key} className="min-w-0">
              <GroupedBarChart
                title={DISTRIBUTION_LABELS[key]}
                categories={categories}
                yLabel="trips per bin"
                formatY={(y) => formatNumber(y, 0)}
                series={COMPARISON_MODES.map((mode) => ({
                  label: modeLabel(data, mode),
                  values: item[mode]?.histogram ?? categories.map(() => null),
                }))}
              />
              <div className="mt-4">
                <DataTable caption={`${DISTRIBUTION_LABELS[key]} percentiles`}>
                  <thead><tr><th>Mode</th><th>n</th><th>p50</th><th>p90</th><th>p95</th><th>max</th></tr></thead>
                  <tbody>
                    {COMPARISON_MODES.map((mode) => {
                      const stats = item[mode];
                      return (
                        <tr key={mode}>
                          <td>{modeLabel(data, mode)}</td>
                          <td className={stats ? undefined : "stats-unknown"}>{stats ? stats.count : UNKNOWN}</td>
                          <Num>{formatNumber(stats?.p50, 1)}</Num>
                          <Num>{formatNumber(stats?.p90, 1)}</Num>
                          <Num>{formatNumber(stats?.p95, 1)}</Num>
                          <Num>{formatNumber(stats?.max, 1)}</Num>
                        </tr>
                      );
                    })}
                  </tbody>
                </DataTable>
              </div>
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
    <StatisticsSection id="intersections" title="Intersections" description={`Per traffic-light controller. Queue: ${data.intersections.queue_measurement}.`} aside={ids.length > 0 ? <Pill>{ids.length} controllers</Pill> : undefined}>
      {ids.length === 0 ? <p className="text-sm text-[#dccdc0]">No per-controller samples in this file.</p> : (
        <DataTable caption="Per-controller statistics">
          <thead>
            <tr><th rowSpan={2}>Traffic light</th>{COMPARISON_MODES.map((mode) => <th key={mode} colSpan={4}>{modeLabel(data, mode)}</th>)}</tr>
            <tr>{COMPARISON_MODES.map((mode) => ["Mean queue", "Max queue", "Mean green (s)", "Decisions"].map((label) => <th key={`${mode}-${label}`}>{label}</th>))}</tr>
          </thead>
          <tbody>
            {ids.map((id) => (
              <tr key={id}>
                <td className="stats-mono">{id}</td>
                {COMPARISON_MODES.map((mode) => {
                  const stats = data.intersections[mode]?.[id];
                  return [
                    <Num key={`${mode}-mean`}>{formatNumber(stats?.mean_queue, 2)}</Num>,
                    <Num key={`${mode}-max`}>{formatNumber(stats?.max_queue, 0)}</Num>,
                    <Num key={`${mode}-green`}>{formatNumber(stats?.mean_green_s, 1)}</Num>,
                    <Num key={`${mode}-decisions`}>{formatNumber(stats?.decision_count, 0)}</Num>,
                  ];
                })}
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </StatisticsSection>
  );
}

export function EmergencySection({ data }: { data: SimulationAnalytics }) {
  const emergency = data.emergency;
  return (
    <StatisticsSection id="emergency" title="Emergency vehicles" description={emergency ? `Emergency vehicle types: ${emergency.vehicle_types.join(", ")}` : undefined}>
      {emergency === null ? <p className="text-sm text-[#dccdc0]">This scenario has no emergency-vehicle trips.</p> : (
        <DataTable caption="Emergency vehicle trips">
          <thead><tr><th>Mode</th><th>Emergency trips</th><th>Emergency avg time loss (s)</th><th>Normal trips</th><th>Normal avg time loss (s)</th></tr></thead>
          <tbody>
            {COMPARISON_MODES.map((mode) => {
              const stats = emergency[mode];
              return (
                <tr key={mode}>
                  <td>{modeLabel(data, mode)}</td>
                  <td className={stats ? undefined : "stats-unknown"}>{stats ? stats.emergency_trip_count : UNKNOWN}</td>
                  <Num>{formatNumber(stats?.emergency_average_time_loss_s, 2)}</Num>
                  <td className={stats ? undefined : "stats-unknown"}>{stats ? stats.normal_trip_count : UNKNOWN}</td>
                  <Num>{formatNumber(stats?.normal_average_time_loss_s, 2)}</Num>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      )}
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
    <StatisticsSection id="validation" title="Validation" aside={<Pill tone={validation.passed ? "good" : "bad"}>{validation.passed ? "Passed" : "Failed"}</Pill>}>
      <DataTable caption="Validation checks per mode">
        <thead><tr><th>Check</th>{COMPARISON_MODES.map((mode) => <th key={mode}>{modeLabel(data, mode)}</th>)}</tr></thead>
        <tbody>
          <tr><td>Passed</td>{COMPARISON_MODES.map((mode) => <td key={mode}><span className="stats-delta" data-tone={validation[mode].passed ? "good" : "bad"}>{validation[mode].passed ? "yes" : "no"}</span></td>)}</tr>
          {VALIDATION_FIELDS.map(([key, label]) => (
            <tr key={key}><td>{label}</td>{COMPARISON_MODES.map((mode) => <Num key={mode}>{formatNumber(validation[mode][key], 0)}</Num>)}</tr>
          ))}
          <tr><td>Stopped by step limit</td>{COMPARISON_MODES.map((mode) => {
            const value = validation[mode].terminated_by_step_limit;
            return <td key={mode} className={value === null ? "stats-unknown" : undefined}>{value === null ? UNKNOWN : value ? "yes" : "no"}</td>;
          })}</tr>
        </tbody>
      </DataTable>
      {validation.errors.length > 0 && (
        <ul className="mt-4 list-disc space-y-1.5 pl-5 text-[13px] leading-6 text-[#ffd6d2] marker:text-[#ff9b93]">{validation.errors.map((error) => <li key={error}>{error}</li>)}</ul>
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
