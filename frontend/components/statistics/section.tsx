/** Shared section wrapper and limitations list used by both dataset kinds. */

import type { ReactNode } from "react";

export function StatisticsSection({ id, title, description, children }: {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="statistics-section mt-6 rounded-xl border border-white/10 p-4">
      <h2 id={`${id}-title`} className="text-base font-medium">{title}</h2>
      {description && <p className="mt-1 text-xs opacity-70">{description}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function LimitationsSection({ limitations }: { limitations: string[] }) {
  return (
    <StatisticsSection id="limitations" title="Limitations">
      {limitations.length === 0
        ? <p className="text-sm">No limitations were recorded in this file.</p>
        : <ul className="list-disc space-y-1 pl-5 text-sm">{limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
    </StatisticsSection>
  );
}

export const tableClass = "statistics-table w-full border-collapse text-left text-sm [&_td]:border-t [&_td]:border-white/10 [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:py-1 [&_th]:font-medium";
