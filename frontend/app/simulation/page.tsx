import { Brand } from "@/components/brand";
import { PublicNav } from "@/components/public-nav";
import { SimulationProvider } from "@/components/simulation/simulation-provider";
import { SimulationWorkspace } from "@/components/simulation/simulation-workspace";

export default function PublicSimulationPage() {
  return (
    <SimulationProvider>
      <main className="app-shell min-h-screen px-3 py-3 text-[#edf3f5] sm:px-5 sm:py-5">
        <div className="mx-auto max-w-[1600px]">
          <header className="surface mb-6 flex flex-wrap items-center justify-between gap-4 rounded-2xl px-4 py-3">
            <Brand context="Public read-only view" />
            <PublicNav active="simulation" />
          </header>
          <SimulationWorkspace access="public" />
        </div>
      </main>
    </SimulationProvider>
  );
}
