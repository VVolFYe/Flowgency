import Link from "next/link";
import { Brand } from "@/components/brand";

export default function SessionExpiredPage() {
  return <main className="app-shell grid min-h-screen place-items-center px-4 text-[#edf3f5]"><div className="surface max-w-lg rounded-[28px] p-8 text-center"><Brand /><p className="eyebrow mt-10">Session expired</p><h1 className="mt-3 text-3xl font-semibold">Sign in again</h1><p className="mt-4 text-sm leading-6 text-[#8b9aa3]">Your Auth0 access token could not be refreshed. No simulation command was sent.</p><div className="mt-7 flex justify-center gap-3"><a href="/auth/logout?returnTo=/access" className="rounded-xl bg-[#7cf2ad] px-4 py-3 text-sm font-semibold text-[#07140c]">Clear session and sign in</a><Link href="/simulation" className="rounded-xl border border-white/10 px-4 py-3 text-sm">Public simulation</Link></div></div></main>;
}
