import Link from "next/link";
import { Brand } from "@/components/brand";

export default function AccessDeniedPage() {
  return <main className="app-shell grid min-h-screen place-items-center px-4 text-[#edf3f5]"><div className="surface max-w-lg rounded-[28px] p-8 text-center"><Brand /><p className="font-mono text-[10px] uppercase tracking-[.19em] text-[#ff727b] mt-10">Access denied</p><h1 className="mt-3 text-3xl font-semibold">Permission required</h1><p className="mt-4 text-sm leading-6 text-[#8b9aa3]">Your Auth0 session is valid, but it does not include the permission required for this workspace.</p><div className="mt-7 flex justify-center gap-3"><a href="/auth/logout" className="rounded-xl border border-white/10 px-4 py-3 text-sm">Logout</a><Link href="/access" className="rounded-xl bg-[#7cf2ad] px-4 py-3 text-sm font-semibold text-[#07140c]">Available access</Link></div></div></main>;
}
