/** Shared presentation primitives for the Statistics page: cards, notices, KPI tiles, tables. */

import type { ReactNode } from "react";
import { UNKNOWN } from "./format";

export function StatisticsSection({ id, title, description, aside, children }: {
  id: string;
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="stats-card">
      <div className="stats-card-head">
        <div className="min-w-0">
          <h2 id={`${id}-title`}>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {aside && <div className="flex flex-wrap items-center gap-2">{aside}</div>}
      </div>
      <div className="stats-card-body">{children}</div>
    </section>
  );
}

export function LimitationsSection({ limitations }: { limitations: string[] }) {
  return (
    <StatisticsSection id="limitations" title="Limitations" description="Recorded by the exporter together with the data.">
      {limitations.length === 0
        ? <p className="text-sm text-[#dccdc0]">No limitations were recorded in this file.</p>
        : <ul className="list-disc space-y-2 pl-5 text-[13px] leading-6 text-[#dccdc0] marker:text-[#b8a393]">{limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
    </StatisticsSection>
  );
}

export type NoticeTone = "info" | "loading" | "error" | "warning";

/** Status, empty and error messages. Always rendered on an opaque surface. */
export function Notice({ tone = "info", role, children }: { tone?: NoticeTone; role?: "status" | "alert"; children: ReactNode }) {
  return (
    <div className="stats-notice" data-tone={tone} role={role}>
      <span aria-hidden className={`stats-notice-dot ${tone === "loading" ? "pulse-soft" : ""}`} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** A short caveat inside a card body. */
export function InlineNote({ role, children }: { role?: "status" | "alert"; children: ReactNode }) {
  return <p className="stats-inline-note" role={role}>{children}</p>;
}

export type PillTone = "neutral" | "good" | "bad" | "warn" | "accent";

export function Pill({ tone = "neutral", children }: { tone?: PillTone; children: ReactNode }) {
  return <span className="stats-pill" data-tone={tone}>{children}</span>;
}

/**
 * KPI tile. `value` is the already formatted number (or UNKNOWN); the unit is
 * kept visible next to it and unknown values are dimmed, never shown as 0.
 */
export function KpiTile({ label, value, unit, foot, emphasis = false }: {
  label: string;
  value: string;
  unit?: string;
  foot?: ReactNode;
  emphasis?: boolean;
}) {
  const unknown = value === UNKNOWN;
  return (
    <article className="stats-kpi" data-emphasis={emphasis}>
      <h3 className="stats-kpi-label">{label}</h3>
      <p className="stats-kpi-value" data-unknown={unknown}>
        <span>{value}</span>
        {unit && !unknown && <span className="stats-kpi-unit">{unit}</span>}
      </p>
      {foot && <p className="stats-kpi-foot">{foot}</p>}
    </article>
  );
}

export function DataTable({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="stats-table-wrap">
      <table className="stats-table">
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}

/** Numeric table cell; unknown values are dimmed. */
export function Num({ children }: { children: string }) {
  return <td className={children === UNKNOWN ? "stats-unknown" : undefined}>{children}</td>;
}

export const tableClass = "stats-table";
