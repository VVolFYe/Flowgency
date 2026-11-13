"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

const links = [
  { href: "/operator", label: "Overview" },
  { href: "/operator/simulation", label: "Live Simulation" },
  { href: "/operator/analytics", label: "Analytics" },
];

export function OperatorNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  const logout = async () => {
    setLoggingOut(true);
    await fetch("/api/operator/logout", { method: "POST" });
    router.replace("/operator/login");
    router.refresh();
  };

  return (
    <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
      <nav aria-label="Operator navigation" className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto rounded-xl border border-white/[.08] bg-[#090e11]/60 p-1 sm:flex-none">
        {links.map((link) => {
          const active = link.href === "/operator" ? pathname === link.href : pathname.startsWith(link.href);
          return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} className={`whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition ${active ? "bg-[#29333a] text-white" : "text-[#8998a0] hover:text-white"}`}>{link.label}</Link>;
        })}
      </nav>
      <button type="button" onClick={logout} disabled={loggingOut} className="rounded-xl border border-white/[.08] px-3 py-2 text-xs font-medium text-[#9cabb4] transition hover:border-white/20 hover:bg-white/[.04] hover:text-white disabled:opacity-50">
        {loggingOut ? "Signing out…" : "Logout"}
      </button>
    </div>
  );
}
