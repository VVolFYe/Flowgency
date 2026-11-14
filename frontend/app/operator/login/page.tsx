import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { LoginForm } from "./login-form";
import { Brand } from "@/components/brand";
import { OPERATOR_SESSION_COOKIE, verifyOperatorSession } from "@/lib/operator-auth";

export default async function OperatorLoginPage() {
  const session = await verifyOperatorSession((await cookies()).get(OPERATOR_SESSION_COOKIE)?.value);
  if (session) redirect("/operator");
  return (
    <main className="app-shell grid min-h-screen place-items-center px-4 py-10 text-[#edf3f5]">
      <div className="surface w-full max-w-md rounded-[28px] p-7 sm:p-9">
        <Brand />
        <p className="eyebrow mt-10">Restricted access</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-.045em]">Operator login</h1>
        <p className="mt-3 text-sm leading-6 text-[#81909a]">Sign in to control the SUMO run and inspect operational analytics.</p>
        <Suspense fallback={<p className="mt-8 text-sm text-[#81909a]">Loading login…</p>}><LoginForm /></Suspense>
        <Link href="/simulation" className="mt-6 block text-center text-xs text-[#81909a] transition hover:text-white">← Return to public live view</Link>
      </div>
    </main>
  );
}
