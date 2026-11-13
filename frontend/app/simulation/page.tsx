import Link from "next/link";
import { PublicNav } from "@/components/public-nav";
import { SimulationProvider } from "@/components/simulation/simulation-provider";
import { SimulationWorkspace } from "@/components/simulation/simulation-workspace";

export default function PublicSimulationPage() {
  return (
    <SimulationProvider>
      <main className="min-h-screen bg-[#080c0f] px-3 py-3 text-[#e8eef4] sm:px-5 sm:py-5">
        <div className="mx-auto max-w-[1600px]">
          <header className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/[.06] bg-[#0d1317] px-4 py-3">
            <Link href="/" className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl border border-[#72e9a6]/25 bg-[#72e9a6]/10 text-xl text-[#72e9a6]">⌁</span><span><span className="block font-semibold">Flowgency</span><span className="block font-mono text-[9px] uppercase tracking-[.18em] text-[#6d7d87]">Public read-only view</span></span></Link>
            <PublicNav active="simulation" />
          </header>
          <SimulationWorkspace access="public" />
        </div>
      </main>
    </SimulationProvider>
  );
}
