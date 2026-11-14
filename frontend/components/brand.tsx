import Link from "next/link";

export function BrandMark({ compact = false }: { compact?: boolean }) {
  const size = compact ? "h-9 w-9 rounded-[11px]" : "h-10 w-10 rounded-xl";
  return (
    <span className={`brand-mark grid ${size} shrink-0 place-items-center bg-[#0e2117] text-[#7cf2ad]`} aria-hidden="true">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
        <path d="M4 7.5h7.2c2.6 0 4.8 2.1 4.8 4.8V20" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M20 4v4.8c0 2-1.6 3.7-3.7 3.7H4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <circle cx="4" cy="7.5" r="1.5" fill="currentColor" />
        <circle cx="4" cy="12.5" r="1.5" fill="currentColor" />
      </svg>
    </span>
  );
}

export function Brand({ href = "/", context }: { href?: string; context?: string }) {
  return (
    <Link href={href} className="group flex items-center gap-3 rounded-xl">
      <BrandMark />
      <span>
        <span className="block text-[15px] font-semibold tracking-[-.01em] text-[#edf3f5]">Flowgency</span>
        {context && <span className="mt-0.5 block font-mono text-[8px] uppercase tracking-[.2em] text-[#71818a]">{context}</span>}
      </span>
    </Link>
  );
}
