import Link from "next/link";
import { PublicNav } from "@/components/public-nav";

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#080c0f] px-5 py-5 text-[#e8eef4]">
      <div className="mx-auto max-w-6xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <Link href="/" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl border border-[#72e9a6]/25 bg-[#72e9a6]/10 text-xl text-[#72e9a6]">⌁</span>
            <span className="font-semibold">Flowgency</span>
          </Link>
          <PublicNav active="home" />
        </header>

        <section className="relative grid min-h-[72vh] items-center gap-12 py-20 lg:grid-cols-[1.05fr_.95fr]">
          <div className="relative z-10">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-[#72e9a6]/20 bg-[#72e9a6]/[.07] px-3 py-1.5 font-mono text-[10px] uppercase tracking-[.18em] text-[#72e9a6]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#72e9a6]" /> UniHack 2026 simulation platform
            </div>
            <h1 className="max-w-3xl text-5xl font-semibold leading-[1.02] tracking-[-.045em] sm:text-7xl">
              Traffic signals that <span className="text-[#72e9a6]">respond.</span>
            </h1>
            <p className="mt-7 max-w-xl text-base leading-7 text-[#8c9ba4] sm:text-lg">
              Flowgency turns camera-grounded observations into SUMO demand, applies deterministic signal control, and makes every decision visible.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/simulation" className="rounded-xl bg-[#72e9a6] px-5 py-3 text-sm font-semibold text-[#06130c] transition hover:bg-[#91f7bf]">Watch live simulation →</Link>
              <Link href="/operator/login" className="rounded-xl border border-white/10 bg-white/[.035] px-5 py-3 text-sm text-[#d7e0e5] transition hover:bg-white/[.07]">Operator access</Link>
            </div>
          </div>

          <div className="relative mx-auto aspect-square w-full max-w-[520px]">
            <div className="absolute inset-[8%] rotate-45 rounded-[50px] border border-[#72e9a6]/10 bg-[#10191d] shadow-2xl shadow-[#72e9a6]/5" />
            <div className="absolute left-1/2 top-0 h-full w-20 -translate-x-1/2 bg-[#1d292f]" />
            <div className="absolute left-0 top-1/2 h-20 w-full -translate-y-1/2 bg-[#1d292f]" />
            <div className="absolute left-1/2 top-1/2 h-20 w-20 -translate-x-1/2 -translate-y-1/2 border border-white/10 bg-[#27353c]" />
            {["left-[47%] top-[16%]", "left-[53%] top-[69%]", "left-[17%] top-[53%]", "left-[72%] top-[47%]"].map((position) => (
              <span key={position} className={`absolute h-7 w-3 rounded-sm bg-[#dce9ef] shadow-[0_0_12px_rgba(114,233,166,.25)] ${position}`} />
            ))}
            <div className="absolute bottom-[16%] right-[13%] rounded-xl border border-white/10 bg-[#0c1317]/90 px-4 py-3 backdrop-blur">
              <p className="font-mono text-[9px] uppercase tracking-[.18em] text-[#6d7d87]">Source of truth</p>
              <p className="mt-1 text-sm text-[#cbd6db]">Eclipse SUMO</p>
            </div>
          </div>
        </section>

        <section className="grid gap-3 border-t border-white/[.07] py-10 md:grid-cols-3">
          {[
            ["01", "Observe", "Camera evidence remains distinct from estimated demand and simulated queues."],
            ["02", "Simulate", "SUMO owns vehicle motion, signal state, queues, and elapsed simulation time."],
            ["03", "Optimize", "Deterministic control preserves safe transitions and keeps decisions explainable."],
          ].map(([number, title, copy]) => (
            <article key={number} className="rounded-2xl border border-white/[.07] bg-[#10171c] p-5">
              <span className="font-mono text-xs text-[#72e9a6]">{number}</span>
              <h2 className="mt-8 text-lg font-medium">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-[#788892]">{copy}</p>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
