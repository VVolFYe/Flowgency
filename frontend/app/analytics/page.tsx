import Link from "next/link";
import { SiteNav } from "@/components/site-nav";

const metrics = ["Average waiting time", "Mean / max queue", "Vehicle throughput", "Emergency travel delay"];

export default function AnalyticsPage() {
  return (
    <main className="min-h-screen bg-[#080c0f] px-4 py-5 text-[#e8eef4] sm:px-6">
      <div className="mx-auto max-w-[1450px]">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Flowgency</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Simulation Results</h1></div>
          <SiteNav active="analytics" />
        </header>

        <section className="mt-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metrics.map((metric) => (
            <article key={metric} className="rounded-2xl border border-white/[.07] bg-[#10171c] p-5">
              <p className="text-xs text-[#788892]">{metric}</p><p className="mt-6 font-mono text-3xl text-[#dce5e9]">—</p><p className="mt-2 text-[10px] uppercase tracking-wider text-[#5f707a]">No completed run metrics</p>
            </article>
          ))}
        </section>

        <section className="mt-4 grid gap-4 lg:grid-cols-2">
          {["Fixed vs Adaptive", "Queue evolution"].map((title) => (
            <article key={title} className="grid min-h-[360px] place-items-center rounded-[24px] border border-white/[.07] bg-[#10171c] p-6 text-center">
              <div><div className="mx-auto flex h-12 w-16 items-end justify-center gap-1.5"><span className="h-5 w-2 rounded-sm bg-white/10" /><span className="h-9 w-2 rounded-sm bg-white/10" /><span className="h-7 w-2 rounded-sm bg-white/10" /><span className="h-11 w-2 rounded-sm bg-white/10" /></div><h2 className="mt-5 text-base font-medium">{title}</h2><p className="mt-2 max-w-sm text-sm leading-6 text-[#788892]">Charts remain empty until the backend exposes comparable run metrics. No demo values are mixed with simulation results.</p></div>
            </article>
          ))}
        </section>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#72e9a6]/15 bg-[#72e9a6]/[.05] px-5 py-4">
          <p className="text-sm text-[#9babae]">Generate live intersection state now; persisted analytics are a later contract.</p>
          <Link href="/simulation" className="text-sm font-medium text-[#72e9a6]">Launch Simulation Lab →</Link>
        </div>
      </div>
    </main>
  );
}
