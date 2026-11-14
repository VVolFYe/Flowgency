import Link from "next/link";

export function PublicNav({ active }: { active?: "home" | "simulation" }) {
  return (
    <nav aria-label="Public navigation" className="flex flex-wrap items-center gap-1 rounded-xl border border-white/[.08] bg-[#10171b]/90 p-1 shadow-lg shadow-black/10 backdrop-blur">
      <Link href="/" aria-current={active === "home" ? "page" : undefined} className={`rounded-lg px-3 py-2 text-xs font-medium transition ${active === "home" ? "bg-[#273139] text-white" : "text-[#8b9aa2] hover:text-white"}`}>About</Link>
      <Link href="/simulation" aria-current={active === "simulation" ? "page" : undefined} className={`rounded-lg px-3 py-2 text-xs font-medium transition ${active === "simulation" ? "bg-[#273139] text-white" : "text-[#8b9aa2] hover:text-white"}`}>Live simulation</Link>
      <Link href="/operator/login" className="rounded-lg px-3 py-2 text-xs font-semibold text-[#7cf2ad] transition hover:bg-[#7cf2ad]/10">Operator <span aria-hidden="true">↗</span></Link>
    </nav>
  );
}
