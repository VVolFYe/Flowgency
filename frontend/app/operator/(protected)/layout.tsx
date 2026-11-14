import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { OperatorNav } from "@/components/operator/operator-nav";
import { Brand } from "@/components/brand";
import { SimulationProvider } from "@/components/simulation/simulation-provider";
import { OPERATOR_SESSION_COOKIE, verifyOperatorSession } from "@/lib/operator-auth";

export default async function OperatorLayout({ children }: { children: React.ReactNode }) {
  const session = await verifyOperatorSession((await cookies()).get(OPERATOR_SESSION_COOKIE)?.value);
  if (!session) redirect("/operator/login");
  return (
    <SimulationProvider collectHistory>
      <main className="app-shell min-h-screen px-3 py-3 text-[#edf3f5] sm:px-5 sm:py-5">
        <div className="mx-auto max-w-[1600px]">
          <header className="surface mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl px-4 py-3">
            <Brand href="/operator" context="Operator control center" />
            <OperatorNav />
          </header>
          {children}
        </div>
      </main>
    </SimulationProvider>
  );
}
