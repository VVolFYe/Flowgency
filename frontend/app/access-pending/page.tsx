import Link from "next/link";
import { Brand } from "@/components/brand";

export default function AccessPendingPage() {
  return <main className="app-shell grid min-h-screen place-items-center px-4 text-[#edf3f5]"><div className="surface max-w-lg rounded-[28px] p-8 text-center"><Brand /><p className="eyebrow mt-10">Access pending</p><h1 className="mt-3 text-3xl font-semibold">Your identity is verified</h1><p className="mt-4 text-sm leading-6 text-[#8b9aa3]">An authorized team member must assign your Auth0 role and permissions. Passwordless first login can create your identity, but it never grants sensitive access automatically.</p><div className="mt-7 flex justify-center gap-3"><a href="/auth/logout" className="rounded-xl border border-white/10 px-4 py-3 text-sm">Logout</a><Link href="/simulation" className="rounded-xl bg-[#7cf2ad] px-4 py-3 text-sm font-semibold text-[#07140c]">Public simulation</Link></div></div></main>;
}
