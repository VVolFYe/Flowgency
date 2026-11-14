import Link from "next/link";
import { Brand } from "@/components/brand";
import { PublicNav } from "@/components/public-nav";

const steps = [
  { number: "01", title: "Observe", copy: "Camera evidence stays separate from estimated demand and simulated queues." },
  { number: "02", title: "Simulate", copy: "SUMO remains the source of truth for vehicle motion, signals and time." },
  { number: "03", title: "Respond", copy: "Deterministic control adapts while preserving explainable, safe transitions." },
];

function IntersectionPreview() {
  return (
    <div className="relative mx-auto aspect-[1.04] w-full max-w-[560px] overflow-hidden rounded-[32px] border border-white/[.08] bg-[#0c1215] shadow-[0_32px_90px_rgba(0,0,0,.38)]">
      <div className="absolute inset-0 opacity-40 [background-image:linear-gradient(rgba(255,255,255,.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.04)_1px,transparent_1px)] [background-size:48px_48px]" />
      <div className="absolute left-1/2 top-[-8%] h-[116%] w-[19%] -translate-x-1/2 bg-[#202c32] shadow-[inset_1px_0_rgba(255,255,255,.06),inset_-1px_0_rgba(255,255,255,.06)]" />
      <div className="absolute left-[-8%] top-1/2 h-[19%] w-[116%] -translate-y-1/2 bg-[#202c32] shadow-[inset_0_1px_rgba(255,255,255,.06),inset_0_-1px_rgba(255,255,255,.06)]" />
      <div className="absolute left-1/2 top-1/2 h-[19%] w-[19%] -translate-x-1/2 -translate-y-1/2 bg-[#29373d]" />
      <div className="absolute left-[45.5%] top-0 h-[40%] border-l border-dashed border-white/20" />
      <div className="absolute bottom-0 left-[54.5%] h-[40%] border-l border-dashed border-white/20" />
      <div className="absolute left-0 top-[54.5%] w-[40%] border-t border-dashed border-white/20" />
      <div className="absolute right-0 top-[45.5%] w-[40%] border-t border-dashed border-white/20" />
      {["left-[47%] top-[15%]", "left-[52%] top-[70%]", "left-[17%] top-[51%]", "left-[74%] top-[45%]"].map((position, index) => (
        <span key={position} className={`absolute h-8 w-3.5 rounded-[4px] border border-white/50 ${index === 1 ? "bg-[#f1bd59] shadow-[0_0_18px_rgba(241,189,89,.3)]" : "bg-[#e7f0f3] shadow-[0_0_18px_rgba(124,242,173,.25)]"} ${position}`} />
      ))}
      <div className="absolute left-5 top-5 flex items-center gap-2 rounded-full border border-white/10 bg-[#080d10]/80 px-3 py-2 backdrop-blur-md">
        <span className="h-1.5 w-1.5 rounded-full bg-[#7cf2ad] shadow-[0_0_10px_#7cf2ad]" />
        <span className="font-mono text-[9px] uppercase tracking-[.18em] text-[#b9c6cb]">Live model</span>
      </div>
      <div className="absolute bottom-5 right-5 border-l-2 border-[#7cf2ad] bg-[#0a1013]/90 px-4 py-3 backdrop-blur-md">
        <p className="font-mono text-[9px] uppercase tracking-[.18em] text-[#71818a]">Source of truth</p>
        <p className="mt-1 text-sm font-medium text-[#d9e3e7]">Eclipse SUMO</p>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <main className="app-shell min-h-screen overflow-hidden px-5 py-5 text-[#edf3f5] sm:px-7 sm:py-6">
      <div className="mx-auto max-w-[1240px]">
        <header className="flex flex-wrap items-center justify-between gap-4"><Brand /><PublicNav active="home" /></header>

        <section className="grid min-h-[76vh] items-center gap-14 py-20 lg:grid-cols-[1.02fr_.98fr] lg:py-24">
          <div className="relative z-10">
            <div className="eyebrow mb-7 flex items-center gap-3"><span className="h-px w-8 bg-[#7cf2ad]" />UniHack 2026 · Traffic simulation</div>
            <h1 className="max-w-[720px] text-[clamp(3.4rem,7vw,6.6rem)] font-semibold leading-[.88] tracking-[-.065em]">Signals with<br /><span className="text-[#7cf2ad]">street sense.</span></h1>
            <p className="mt-8 max-w-[590px] text-base leading-7 text-[#98a6ad] sm:text-lg sm:leading-8">From camera-grounded observations to live SUMO decisions. Flowgency makes adaptive traffic control visible, deterministic and easy to explain.</p>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <Link href="/simulation" className="rounded-xl bg-[#7cf2ad] px-5 py-3.5 text-sm font-semibold text-[#07140c] transition hover:-translate-y-0.5 hover:bg-[#98f7be]">Watch live simulation <span aria-hidden="true">↗</span></Link>
              <Link href="/operator/login" className="rounded-xl border border-white/10 bg-[#10171b] px-5 py-3.5 text-sm font-medium text-[#d6e0e4] transition hover:border-white/20 hover:bg-[#151e23]">Operator access</Link>
            </div>
            <dl className="mt-12 flex flex-wrap gap-x-10 gap-y-5 border-t border-white/[.08] pt-6">
              <div><dt className="font-mono text-[9px] uppercase tracking-[.18em] text-[#667780]">Control</dt><dd className="mt-1 text-sm text-[#c6d1d6]">Deterministic</dd></div>
              <div><dt className="font-mono text-[9px] uppercase tracking-[.18em] text-[#667780]">Simulation</dt><dd className="mt-1 text-sm text-[#c6d1d6]">Server-owned</dd></div>
              <div><dt className="font-mono text-[9px] uppercase tracking-[.18em] text-[#667780]">Telemetry</dt><dd className="mt-1 text-sm text-[#c6d1d6]">WebSocket live</dd></div>
            </dl>
          </div>
          <IntersectionPreview />
        </section>

        <section className="border-t border-white/[.08] py-12 sm:py-16" aria-labelledby="pipeline-title">
          <div className="mb-9 grid gap-3 md:grid-cols-[.75fr_1.25fr] md:items-end">
            <div><p className="eyebrow">The control loop</p><h2 id="pipeline-title" className="mt-3 text-2xl font-semibold tracking-[-.035em] sm:text-3xl">Evidence in. Decisions out.</h2></div>
            <p className="max-w-xl text-sm leading-6 text-[#84939b] md:justify-self-end">Every layer keeps its own responsibility, so an observed vehicle never quietly becomes a simulated queue.</p>
          </div>
          <div className="grid gap-px overflow-hidden rounded-2xl border border-white/[.08] bg-white/[.08] md:grid-cols-3">
            {steps.map((step) => (
              <article key={step.number} className="bg-[#0f161a] p-6 sm:p-7">
                <div className="flex items-center justify-between"><span className="font-mono text-[10px] tracking-[.16em] text-[#7cf2ad]">{step.number}</span><span className="h-1.5 w-1.5 rounded-full bg-[#34434a]" /></div>
                <h3 className="mt-12 text-xl font-semibold tracking-[-.02em]">{step.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[#7f8f97]">{step.copy}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
