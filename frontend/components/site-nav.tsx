import Link from "next/link";

export function SiteNav({ active }: { active?: "dashboard" | "simulation" | "analytics" }) {
  const links = [
    { href: "/dashboard", label: "Overview", key: "dashboard" },
    { href: "/simulation", label: "Simulation", key: "simulation" },
    { href: "/analytics", label: "Analytics", key: "analytics" },
  ] as const;

  return (
    <nav aria-label="Primary navigation" className="flex flex-wrap items-center gap-1 rounded-xl border border-white/[.07] bg-white/[.025] p-1">
      {links.map((link) => (
        <Link
          key={link.key}
          href={link.href}
          className={`rounded-lg px-3 py-2 text-xs transition ${active === link.key ? "bg-white/[.09] text-white" : "text-[#83929b] hover:text-white"}`}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
