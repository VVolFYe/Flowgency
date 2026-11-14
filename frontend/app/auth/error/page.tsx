import Link from "next/link";
import { Brand } from "@/components/brand";

export default async function AuthErrorPage({ searchParams }: { searchParams: Promise<{ code?: string }> }) {
  const { code } = await searchParams;
  return <main className="app-shell grid min-h-screen place-items-center px-4 text-[#edf3f5]"><div className="surface max-w-lg rounded-[28px] p-8 text-center"><Brand /><p className="mt-10 font-mono text-[10px] uppercase tracking-[.19em] text-[#ff727b]">Auth0 error</p><h1 className="mt-3 text-3xl font-semibold">Sign-in could not be completed</h1><p className="mt-4 text-sm leading-6 text-[#8b9aa3]">The authentication callback or encrypted application session was invalid. Try signing in again; if the problem continues, verify the callback URL and local Auth0 configuration.</p><p className="mt-4 font-mono text-[10px] text-[#667781]">Reference: {code || "authentication_error"}</p><div className="mt-7 flex justify-center gap-3"><Link href="/access" className="rounded-xl bg-[#7cf2ad] px-4 py-3 text-sm font-semibold text-[#07140c]">Try again</Link><Link href="/simulation" className="rounded-xl border border-white/10 px-4 py-3 text-sm">Public simulation</Link></div></div></main>;
}
