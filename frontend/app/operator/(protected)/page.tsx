"use client";

import Link from "next/link";
import { ConnectionBadge, formatTime } from "@/components/simulation/simulation-workspace";
import { useSimulation } from "@/components/simulation/simulation-provider";

export default function OperatorOverviewPage() {
  const { status, snapshot, connection, error, history } = useSimulation();
  const vehicleCount = snapshot?.vehicles ? snapshot.vehicles.length : null;
  const queues = Object.values(snapshot?.queue_lengths_by_approach ?? {}).map((value) => value?.vehicles).filter((value): value is number => value != null);
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Operator workspace</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Overview</h1><p className="mt-2 text-sm text-[#81909a]">One authoritative view of the current SUMO service and browser session.</p></div><ConnectionBadge connection={connection} stale={connection !== "connected" && snapshot !== null} /></div>
      {error && <div className="mt-5 rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-4 py-3 text-sm text-[#ffabb1]">{error}</div>}
      <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Simulation state", status.state],
          ["Simulation time", formatTime(snapshot?.simulation_time_s ?? status.simulation_time_s)],
          ["Active vehicles", vehicleCount ?? "—"],
          ["Largest current queue", queues.length ? Math.max(...queues) : "—"],
        ].map(([label, value]) => <article key={label} className="rounded-2xl border border-white/[.07] bg-[#10171c] p-5"><p className="text-xs text-[#788892]">{label}</p><p className="mt-6 truncate font-mono text-2xl capitalize text-[#dce5e9]">{value}</p></article>)}
      </section>
      <section className="mt-4 grid gap-4 lg:grid-cols-2">
        <article className="rounded-[24px] border border-white/[.07] bg-[#10171c] p-6"><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Current snapshot</p><h2 className="mt-2 text-lg font-medium">Operational identifiers</h2><dl className="mt-5 space-y-3 text-sm">{[["Run", snapshot?.run_id], ["Scenario", snapshot?.scenario_id], ["Intersection", snapshot?.intersection_id], ["Signal phase", snapshot?.current_phase_id], ["Signal state", snapshot?.traffic_light_state], ["Coordinate system", snapshot?.coordinate_system]].map(([label, value]) => <div key={label} className="flex justify-between gap-4 border-b border-white/[.05] pb-3"><dt className="text-[#73838d]">{label}</dt><dd className="max-w-[65%] truncate font-mono text-xs text-[#c5d0d6]" title={value ?? undefined}>{value ?? "—"}</dd></div>)}</dl></article>
        <article className="rounded-[24px] border border-white/[.07] bg-[#10171c] p-6"><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Quick access</p><h2 className="mt-2 text-lg font-medium">Control and inspect</h2><div className="mt-5 grid gap-3"><Link href="/operator/simulation" className="rounded-xl border border-[#72e9a6]/20 bg-[#72e9a6]/[.06] p-4 transition hover:bg-[#72e9a6]/10"><span className="text-sm font-medium text-[#72e9a6]">Open Live Simulation →</span><span className="mt-1 block text-xs text-[#7f909b]">Start, pause, resume, reset or stop the run.</span></Link><Link href="/operator/analytics" className="rounded-xl border border-white/[.07] bg-white/[.025] p-4 transition hover:bg-white/[.05]"><span className="text-sm font-medium">Open Analytics →</span><span className="mt-1 block text-xs text-[#7f909b]">{history.length ? `${history.length} real snapshots in this browser session.` : "Waiting for real snapshot data."}</span></Link></div></article>
      </section>
    </div>
  );
}
