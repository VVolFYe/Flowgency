import Link from "next/link";

export function PublicNav({ active }: { active?: "home" | "simulation" }) {
  return (
    <nav aria-label="Public navigation" className="flex flex-wrap items-center gap-1 rounded-xl border border-white/[.07] bg-white/[.025] p-1">
      <Link href="/" className={`rounded-lg px-3 py-2 text-xs transition ${active === "home" ? "bg-white/[.09] text-white" : "text-[#83929b] hover:text-white"}`}>About</Link>
      <Link href="/simulation" className={`rounded-lg px-3 py-2 text-xs transition ${active === "simulation" ? "bg-white/[.09] text-white" : "text-[#83929b] hover:text-white"}`}>Live simulation</Link>
      <Link href="/operator/login" className="rounded-lg px-3 py-2 text-xs font-medium text-[#72e9a6] transition hover:bg-[#72e9a6]/10">Operator</Link>
    </nav>
  );
}
