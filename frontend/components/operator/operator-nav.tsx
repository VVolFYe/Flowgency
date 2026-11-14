"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function OperatorNav({ workspace }: { workspace: "analyst" | "operator" }) {
  const pathname = usePathname();
  const links = [
    { href: `/${workspace}`, label: "Overview" },
    { href: `/${workspace}/simulation`, label: "Live Simulation" },
    { href: `/${workspace}/analytics`, label: "Analytics" },
    { href: `/${workspace}/statistics`, label: "Statistics" },
    ...(workspace === "operator" ? [{ href: "/operator/benchmarks", label: "Benchmarks" }] : []),
  ];

  return (
    <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
      <nav aria-label="Operator navigation" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto rounded-xl border border-white/[.08] bg-[#1b120e]/60 p-1 sm:flex-none">
        {links.map((link) => {
          const active = link.href === `/${workspace}` ? pathname === link.href : pathname.startsWith(link.href);
          return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} className={`whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition ${active ? "bg-[#50382b] text-white" : "text-[#bea99a] hover:text-white"}`}>{link.label}</Link>;
        })}
      </nav>
      <a href="/auth/logout" className="rounded-xl border border-white/[.08] px-3 py-2 text-xs font-medium text-[#9cabb4] transition hover:border-white/20 hover:bg-white/[.04] hover:text-white">Logout</a>
    </div>
  );
}
