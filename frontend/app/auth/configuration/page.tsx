import Link from "next/link";
import { Brand } from "@/components/brand";
import { missingAuth0Configuration } from "@/lib/auth0";

export default function AuthConfigurationPage() {
  const missing = missingAuth0Configuration();
  return <main className="app-shell grid min-h-screen place-items-center px-4 text-[#edf3f5]"><div className="surface max-w-xl rounded-[28px] p-8"><Brand /><p className="eyebrow mt-10">Configuration required</p><h1 className="mt-3 text-3xl font-semibold">Auth0 is not ready</h1><p className="mt-3 text-sm leading-6 text-[#8b9aa3]">Create <span className="font-mono">frontend/.env.local</span> from the example. Missing server variables:</p><p className="mt-4 rounded-xl bg-black/20 p-4 font-mono text-xs leading-6 text-[#f1d18a]">{missing.length ? missing.join("\n") : "Restart the Next.js server to load the configuration."}</p><p className="mt-4 text-xs leading-5 text-[#71818a]">No credentials are hardcoded and public pages remain available.</p><Link href="/" className="mt-7 inline-block rounded-xl border border-white/10 px-4 py-3 text-sm">Return home</Link></div></main>;
}
