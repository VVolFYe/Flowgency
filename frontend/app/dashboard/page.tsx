import Link from "next/link";
import { SiteNav } from "@/components/site-nav";

const candidates = [
  ["J1", "Camberwell New Rd / Brixton Rd", "JamCams_00001.04503"],
  ["J2", "Camberwell New Rd / Vassall Rd", "JamCams_00001.04339"],
  ["J3", "Brixton Rd / Vassall Rd / Caldwell St", "JamCams_00001.04523"],
  ["J4", "Clapham Rd / Caldwell St", "JamCams_00001.04611"],
  ["J5", "Kennington Park Rd / Kennington Oval", "JamCams_00001.04345"],
];

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-[#080c0f] px-4 py-5 text-[#e8eef4] sm:px-6">
      <div className="mx-auto max-w-[1450px]">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Flowgency</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Traffic Overview</h1></div>
          <SiteNav active="dashboard" />
        </header>

        <section className="mt-7 grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div className="relative min-h-[560px] overflow-hidden rounded-[24px] border border-white/[.07] bg-[#10171c] p-5">
            <div className="absolute inset-0 opacity-30" style={{ backgroundImage: "linear-gradient(rgba(125,153,166,.13) 1px, transparent 1px), linear-gradient(90deg, rgba(125,153,166,.13) 1px, transparent 1px)", backgroundSize: "42px 42px" }} />
            <div className="relative z-10 flex h-full min-h-[520px] flex-col items-center justify-center text-center">
              <span className="grid h-14 w-14 place-items-center rounded-2xl border border-[#72e9a6]/20 bg-[#72e9a6]/10 text-2xl text-[#72e9a6]">⌖</span>
              <h2 className="mt-5 text-xl font-medium">London network map pending validation</h2>
              <p className="mt-3 max-w-lg text-sm leading-6 text-[#81919a]">The repository identifies five candidate JamCam locations around Oval, but their coordinates, coverage, and SUMO junction mappings are not yet validated. No marker is placed by assumption.</p>
              <Link href="/simulation" className="mt-6 rounded-xl bg-[#72e9a6] px-4 py-2.5 text-sm font-semibold text-[#06130c]">Open validated simulation</Link>
            </div>
          </div>

          <aside className="rounded-[24px] border border-white/[.07] bg-[#10171c] p-5">
            <div className="flex items-start justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Candidate references</p><h2 className="mt-1 text-base font-medium">Oval area · 5 cameras</h2></div><span className="rounded-full border border-[#f0bc55]/20 bg-[#f0bc55]/10 px-2 py-1 text-[9px] uppercase tracking-wider text-[#f0bc55]">Unverified</span></div>
            <div className="mt-5 space-y-2">
              {candidates.map(([id, location, camera]) => (
                <article key={id} className="rounded-xl border border-white/[.05] bg-white/[.025] p-3">
                  <div className="flex gap-3"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-white/[.06] font-mono text-xs text-[#72e9a6]">{id}</span><div><h3 className="text-sm text-[#ccd6db]">{location}</h3><p className="mt-1 font-mono text-[10px] text-[#687983]">{camera}</p></div></div>
                  <p className="mt-3 border-t border-white/[.05] pt-2 text-[10px] uppercase tracking-wider text-[#62737d]">Live status unavailable</p>
                </article>
              ))}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
