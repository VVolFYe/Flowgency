import Link from "next/link";

export function PublicNav({ active }: { active?: "home" | "simulation" }) {
  return (
    <nav aria-label="Public navigation" className="flex flex-wrap items-center gap-1 rounded-xl border border-white/[.08] bg-[#2d2018]/90 p-1 shadow-lg shadow-black/10 backdrop-blur">
      <Link href="/" aria-current={active === "home" ? "page" : undefined} className={`rounded-lg px-3 py-3 text-xs font-medium transition ${active === "home" ? "bg-[#50382b] text-white" : "text-[#bea99a] hover:text-white"}`}>About</Link>
      <Link href="/simulation" aria-current={active === "simulation" ? "page" : undefined} className={`rounded-lg px-3 py-3 text-xs font-medium transition ${active === "simulation" ? "bg-[#50382b] text-white" : "text-[#bea99a] hover:text-white"}`}>Live simulation</Link>
      <Link href="/access" className="rounded-lg px-3 py-3 text-xs font-semibold text-[#ffd0ae] transition hover:bg-[#ffac79]/10">Operator <span aria-hidden="true">↗</span></Link>
    </nav>
  );
}
