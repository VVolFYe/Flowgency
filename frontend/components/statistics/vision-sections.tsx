/** One component per section of a vision (gate-mode camera) analytics file. */

import type { VisionAnalytics } from "@/lib/contracts";
import { GroupedBarChart, LineChart } from "./charts";
import { formatClock, formatNumber, UNKNOWN } from "./format";
import { DataTable, KpiTile, LimitationsSection, Num, Pill, StatisticsSection } from "./section";

export function SourceInfo({ data }: { data: VisionAnalytics }) {
  const { source } = data;
  return (
    <StatisticsSection id="source" title="Source" description="Camera footage processed by the vision pipeline in gate mode." aside={<Pill tone="accent">{data.arms.length} arms</Pill>}>
      <div className="grid gap-x-10 gap-y-4 lg:grid-cols-2">
        <dl className="stats-dl">
          <dt>Label</dt><dd>{source.label}</dd>
          <dt>Duration</dt><dd>{formatNumber(source.duration_s, 0)} s ({source.duration_definition})</dd>
          <dt>Frame rate</dt><dd>{source.fps === null ? UNKNOWN : `${formatNumber(source.fps, 3)} fps`}</dd>
        </dl>
        <dl className="stats-dl">
          <dt>Model</dt><dd className="stats-mono">{source.model_id}</dd>
          <dt>Arms</dt><dd>{data.arms.join(", ")}</dd>
          <dt>Sample README</dt><dd className="stats-mono">{source.sample_readme ?? UNKNOWN}</dd>
        </dl>
      </div>
    </StatisticsSection>
  );
}

/** Placeholder slot: the demo video is not stored in git. */
export function VideoPlaceholder({ data }: { data: VisionAnalytics }) {
  return (
    <StatisticsSection id="video" title="Demo video" description="The processed clip is not stored in the repository.">
      <figure data-slot="demo-video" className="grid aspect-video max-h-[360px] w-full place-items-center rounded-xl border border-dashed border-white/20 bg-[#160e0a] px-6 text-center">
        <figcaption className="text-sm leading-6 text-[#dccdc0]">
          Video placeholder — the clip for “{data.source.label}” is not in the repository.
          <br />
          <span className="text-xs text-[#b8a393]">Drop a &lt;video&gt; element here when a hosted file is available.</span>
        </figcaption>
      </figure>
    </StatisticsSection>
  );
}

export function TotalsKpis({ data }: { data: VisionAnalytics }) {
  return (
    <section aria-label="Totals per arm">
      <h2 className="sr-only">Totals per arm</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.arms.map((arm) => {
          const totals = data.totals[arm];
          return (
            <KpiTile
              key={arm}
              label={`${arm} · entered`}
              value={formatNumber(totals?.entered, 0)}
              unit="veh"
              foot={<span>discharged <strong>{formatNumber(totals?.discharged, 0)}</strong> · peak on approach <strong>{formatNumber(totals?.peak_vehicles_on_approach, 0)}</strong></span>}
            />
          );
        })}
      </div>
    </section>
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
      <LineChart title="Vehicles on approach per arm" xLabel="video time" yLabel="vehicles" formatX={formatClock} formatY={(y) => formatNumber(y, 0)} series={series} />
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
        formatY={(y) => formatNumber(y, 0)}
        series={data.arms.map((arm) => ({ label: arm, values: windows.map((window) => window.entered[arm] ?? null) }))}
      />
      <div className="mt-5">
        <DataTable caption="Entered and discharged vehicles per window and arm">
          <thead>
            <tr><th rowSpan={2}>Window</th>{data.arms.map((arm) => <th key={arm} colSpan={2}>{arm}</th>)}</tr>
            <tr>{data.arms.map((arm) => [<th key={`${arm}-in`}>entered</th>, <th key={`${arm}-out`}>discharged</th>])}</tr>
          </thead>
          <tbody>
            {windows.map((window, index) => (
              <tr key={window.start_s}>
                <td className="stats-mono">{categories[index]}{window.partial ? " (partial)" : ""}</td>
                {data.arms.map((arm) => [
                  <Num key={`${arm}-in`}>{formatNumber(window.entered[arm], 0)}</Num>,
                  <Num key={`${arm}-out`}>{formatNumber(window.discharged[arm], 0)}</Num>,
                ])}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </div>
    </StatisticsSection>
  );
}

export function TotalsTable({ data }: { data: VisionAnalytics }) {
  return (
    <StatisticsSection id="totals" title="Totals per arm" description="Cumulative gate counts over the whole clip.">
      <DataTable caption="Totals per arm">
        <thead><tr><th>Arm</th><th>Entered</th><th>Discharged</th><th>Peak on approach</th></tr></thead>
        <tbody>
          {data.arms.map((arm) => {
            const totals = data.totals[arm];
            return (
              <tr key={arm}>
                <td>{arm}</td>
                <Num>{formatNumber(totals?.entered, 0)}</Num>
                <Num>{formatNumber(totals?.discharged, 0)}</Num>
                <Num>{formatNumber(totals?.peak_vehicles_on_approach, 0)}</Num>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    </StatisticsSection>
  );
}

export function TurningMatrix({ data }: { data: VisionAnalytics }) {
  const matrix = data.turning_matrix;
  return (
    <StatisticsSection id="turning" title="Turning matrix" description={`Origin arm → exit arm from ${matrix.total_exits} intersection exits; ${matrix.unknown_origin_exits} have an unknown origin.`}>
      <DataTable caption="Turning matrix">
        <thead><tr><th>From \ To</th>{matrix.exits.map((exit) => <th key={exit}>{exit}</th>)}<th>Total</th></tr></thead>
        <tbody>
          {matrix.origins.map((origin) => {
            const row = matrix.counts[origin] ?? {};
            return (
              <tr key={origin}>
                <th scope="row">{origin}</th>
                {matrix.exits.map((exit) => <Num key={exit}>{formatNumber(row[exit], 0)}</Num>)}
                <td className="font-semibold">{Object.values(row).reduce((sum, value) => sum + value, 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    </StatisticsSection>
  );
}

export function VisionStatistics({ data }: { data: VisionAnalytics }) {
  return (
    <>
      <section aria-labelledby="vision-title" className="stats-card">
        <div className="stats-card-body">
          <p className="stats-group-title">Vision · camera gate counts</p>
          <h2 id="vision-title" className="mt-2 text-xl font-bold tracking-[-.02em] text-[#fff4eb] sm:text-2xl">{data.source.label}</h2>
        </div>
      </section>
      <TotalsKpis data={data} />
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
