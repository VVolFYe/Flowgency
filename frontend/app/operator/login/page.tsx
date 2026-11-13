import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LoginForm } from "./login-form";
import { OPERATOR_SESSION_COOKIE, verifyOperatorSession } from "@/lib/operator-auth";

export default async function OperatorLoginPage() {
  const session = await verifyOperatorSession((await cookies()).get(OPERATOR_SESSION_COOKIE)?.value);
  if (session) redirect("/operator");
  return (
    <main className="grid min-h-screen place-items-center bg-[#080c0f] px-4 py-10 text-[#e8eef4]">
      <div className="w-full max-w-md rounded-[28px] border border-white/[.08] bg-[#10171c] p-7 shadow-2xl shadow-black/30 sm:p-9">
        <Link href="/" className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl border border-[#72e9a6]/25 bg-[#72e9a6]/10 text-xl text-[#72e9a6]">⌁</span><span className="font-semibold">Flowgency</span></Link>
        <p className="mt-9 font-mono text-[10px] uppercase tracking-[.2em] text-[#72e9a6]">Restricted access</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Operator login</h1>
        <p className="mt-3 text-sm leading-6 text-[#81909a]">Sign in to control the SUMO run and inspect operational analytics.</p>
        <Suspense fallback={<p className="mt-8 text-sm text-[#81909a]">Loading login…</p>}><LoginForm /></Suspense>
        <Link href="/simulation" className="mt-6 block text-center text-xs text-[#81909a] hover:text-white">Return to public live view</Link>
      </div>
    </main>
  );
}
