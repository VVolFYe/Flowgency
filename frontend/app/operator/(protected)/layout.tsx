import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { OperatorNav } from "@/components/operator/operator-nav";
import { SimulationProvider } from "@/components/simulation/simulation-provider";
import { OPERATOR_SESSION_COOKIE, verifyOperatorSession } from "@/lib/operator-auth";

export default async function OperatorLayout({ children }: { children: React.ReactNode }) {
  const session = await verifyOperatorSession((await cookies()).get(OPERATOR_SESSION_COOKIE)?.value);
  if (!session) redirect("/operator/login");
  return (
    <SimulationProvider collectHistory>
      <main className="min-h-screen bg-[#080c0f] px-3 py-3 text-[#e8eef4] sm:px-5 sm:py-5">
        <div className="mx-auto max-w-[1600px]">
          <header className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/[.06] bg-[#0d1317] px-4 py-3">
            <Link href="/operator" className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl border border-[#72e9a6]/25 bg-[#72e9a6]/10 text-xl text-[#72e9a6]">⌁</span><span><span className="block font-semibold">Flowgency</span><span className="block font-mono text-[9px] uppercase tracking-[.18em] text-[#6d7d87]">Operator control center</span></span></Link>
            <OperatorNav />
          </header>
          {children}
        </div>
      </main>
    </SimulationProvider>
  );
}
