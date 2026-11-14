/** One component per section of a vision (gate-mode camera) analytics file. */

import type { VisionAnalytics } from "@/lib/contracts";
import { GroupedBarChart, LineChart } from "./charts";
import { formatClock, formatNumber, UNKNOWN } from "./format";
import { LimitationsSection, StatisticsSection, tableClass } from "./section";

export function SourceInfo({ data }: { data: VisionAnalytics }) {
  const { source } = data;
  return (
    <StatisticsSection id="source" title="Source">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        <dt>Label</dt><dd>{source.label}</dd>
        <dt>Duration</dt><dd>{formatNumber(source.duration_s, 0)} s ({source.duration_definition})</dd>
        <dt>Frame rate</dt><dd>{source.fps === null ? UNKNOWN : `${formatNumber(source.fps, 3)} fps`}</dd>
        <dt>Model</dt><dd>{source.model_id}</dd>
        <dt>Arms</dt><dd>{data.arms.join(", ")}</dd>
        <dt>Sample README</dt><dd>{source.sample_readme ?? UNKNOWN}</dd>
      </dl>
    </StatisticsSection>
  );
}

/** Placeholder slot: the demo video is not stored in git. */
export function VideoPlaceholder({ data }: { data: VisionAnalytics }) {
  return (
    <StatisticsSection id="video" title="Demo video">
      <figure data-slot="demo-video" className="statistics-video-placeholder grid aspect-video place-items-center rounded-lg border border-dashed border-white/20 text-center text-sm">
        <figcaption>
          Video placeholder — the clip for “{data.source.label}” is not in the repository.
          <br />
          <span className="text-xs opacity-70">Drop a &lt;video&gt; element here when a hosted file is available.</span>
        </figcaption>
      </figure>
    </StatisticsSection>
  );
}

export function ArmTimeSeries({ data }: { data: VisionAnalytics }) {
  const { t_s: times, vehicles_on_approach: onApproach, in_intersection: inIntersection } = data.timeseries;
  const series = [
    ...data.arms.map((arm) => ({ label: arm, points: times.map((t, index) => ({ x: t, y: onApproach[arm]?.[index] ?? null })) })),
    { label: "in intersection", points: times.map((t, index) => ({ x: t, y: inIntersection[index] ?? null })) },
  ];
  return (
    <StatisticsSection id="arm-timeseries" title="Vehicles per arm over time" description="Per second of video. vehicles_on_approach includes moving and queued vehicles.">
      <LineChart title="Vehicles on approach per arm" xLabel="video time" yLabel="vehicles" formatX={formatClock} series={series} />
    </StatisticsSection>
  );
}

function windowLabel(start: number, end: number) {
  return `${formatClock(start)}–${formatClock(end)}`;
}

export function FlowPerMinute({ data }: { data: VisionAnalytics }) {
  const windows = data.flow_per_minute;
  const categories = windows.map((window) => windowLabel(window.start_s, window.end_s));
  return (
    <StatisticsSection id="flow" title="Flow per minute" description="Differences of the cumulative gate totals; a partial last window is marked.">
      <GroupedBarChart
        title="Vehicles entering each arm per window"
        categories={categories}
        yLabel="vehicles entered"
        series={data.arms.map((arm) => ({ label: arm, values: windows.map((window) => window.entered[arm] ?? null) }))}
      />
      <div className="mt-3 overflow-x-auto">
        <table className={tableClass}>
          <thead>
            <tr><th rowSpan={2}>Window</th>{data.arms.map((arm) => <th key={arm} colSpan={2}>{arm}</th>)}</tr>
            <tr>{data.arms.map((arm) => [<th key={`${arm}-in`}>entered</th>, <th key={`${arm}-out`}>discharged</th>])}</tr>
          </thead>
          <tbody>
            {windows.map((window, index) => (
              <tr key={window.start_s}>
                <td>{categories[index]}{window.partial ? " (partial)" : ""}</td>
                {data.arms.map((arm) => [
                  <td key={`${arm}-in`}>{formatNumber(window.entered[arm], 0)}</td>,
                  <td key={`${arm}-out`}>{formatNumber(window.discharged[arm], 0)}</td>,
                ])}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </StatisticsSection>
  );
}

export function TotalsTable({ data }: { data: VisionAnalytics }) {
  return (
    <StatisticsSection id="totals" title="Totals per arm">
      <table className={tableClass}>
        <thead><tr><th>Arm</th><th>Entered</th><th>Discharged</th><th>Peak on approach</th></tr></thead>
        <tbody>
          {data.arms.map((arm) => {
            const totals = data.totals[arm];
            return (
              <tr key={arm}>
                <td>{arm}</td>
                <td>{formatNumber(totals?.entered, 0)}</td>
                <td>{formatNumber(totals?.discharged, 0)}</td>
                <td>{formatNumber(totals?.peak_vehicles_on_approach, 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </StatisticsSection>
  );
}

export function TurningMatrix({ data }: { data: VisionAnalytics }) {
  const matrix = data.turning_matrix;
  return (
    <StatisticsSection id="turning" title="Turning matrix" description={`Origin arm → exit arm from ${matrix.total_exits} intersection exits; ${matrix.unknown_origin_exits} have an unknown origin.`}>
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead><tr><th>From \ To</th>{matrix.exits.map((exit) => <th key={exit}>{exit}</th>)}<th>Total</th></tr></thead>
          <tbody>
            {matrix.origins.map((origin) => {
              const row = matrix.counts[origin] ?? {};
              return (
                <tr key={origin}>
                  <th scope="row">{origin}</th>
                  {matrix.exits.map((exit) => <td key={exit}>{formatNumber(row[exit], 0)}</td>)}
                  <td>{Object.values(row).reduce((sum, value) => sum + value, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </StatisticsSection>
  );
}

export function VisionStatistics({ data }: { data: VisionAnalytics }) {
  return (
    <>
      <header className="statistics-header mt-6"><h2 className="text-xl font-semibold">{data.source.label}</h2></header>
      <SourceInfo data={data} />
      <VideoPlaceholder data={data} />
      <ArmTimeSeries data={data} />
      <FlowPerMinute data={data} />
      <TotalsTable data={data} />
      <TurningMatrix data={data} />
      <LimitationsSection limitations={data.limitations} />
    </>
  );
}
