import Link from "next/link";
import { redirect } from "next/navigation";
import { Brand } from "@/components/brand";
import { getAuthorization, permissions } from "@/lib/authorization";
import { auth0Configured } from "@/lib/auth0";

function safeNext(value: string | undefined, fallback: string) {
  return value?.startsWith("/") && !value.startsWith("//") ? value : fallback;
}

export default async function AccessPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  const authorization = await getAuthorization();
  if ("sessionError" in authorization && authorization.sessionError) redirect("/auth/error?code=session_invalid");
  if ("tokenError" in authorization && authorization.tokenError) redirect("/auth/session-expired");
  if (authorization.authenticated) {
    const operator = authorization.permissions.has(permissions.simulationControl);
    const analyst = authorization.permissions.has(permissions.simulationRead) && authorization.permissions.has(permissions.analyticsRead);
    return (
      <main className="app-shell grid min-h-screen place-items-center px-4 py-10 text-[#fff1e5]">
        <div className="surface w-full max-w-xl rounded-[28px] p-7 text-center sm:p-9"><Brand /><p className="eyebrow mt-10">Session active</p><h1 className="mt-3 text-3xl font-semibold">Welcome back</h1><p className="mt-3 text-sm text-[#bea99a]">Continue with the access granted by your Auth0 permissions.</p><div className="mt-8 flex flex-wrap justify-center gap-3">{operator && <Link href={safeNext(next, "/operator")} className="rounded-xl bg-[#ffbc90] px-5 py-3 text-sm font-semibold text-[#321b10]">Open Operator</Link>}{analyst && <Link href={operator ? "/analyst" : safeNext(next, "/analyst")} className="rounded-xl border border-white/10 px-5 py-3 text-sm">Open Analyst</Link>}{!operator && !analyst && <Link href="/access-pending" className="rounded-xl border border-[#f1bd59]/30 px-5 py-3 text-sm text-[#f1d18a]">View access status</Link>}<a href="/auth/logout" className="rounded-xl border border-white/10 px-5 py-3 text-sm text-[#9cabb4]">Logout</a></div></div>
      </main>
    );
  }

  const configured = auth0Configured();
  const analystReturnTo = safeNext(next?.startsWith("/analyst") ? next : undefined, "/analyst");
  const operatorReturnTo = safeNext(next?.startsWith("/operator") ? next : undefined, "/operator");
  const analystConnection = encodeURIComponent(process.env.AUTH0_ANALYST_CONNECTION || "email");
  const operatorConnection = encodeURIComponent(process.env.AUTH0_OPERATOR_CONNECTION || "Username-Password-Authentication");
  return (
    <main className="app-shell min-h-screen px-4 py-8 text-[#fff1e5] sm:px-7">
      <div className="mx-auto max-w-5xl"><Brand /><div className="mx-auto max-w-2xl py-14 text-center"><p className="eyebrow">Flowgency access</p><h1 className="mt-4 text-4xl font-semibold tracking-[-.045em] sm:text-5xl">Choose your workspace</h1><p className="mt-4 text-sm leading-6 text-[#bea99a]">Authentication is handled by Auth0 Universal Login. Flowgency never collects or stores your password or one-time code.</p></div>
        {!configured && <div role="alert" className="mx-auto mb-6 max-w-3xl rounded-xl border border-[#f1bd59]/30 bg-[#f1bd59]/10 px-4 py-3 text-sm text-[#f1d18a]">Auth0 is not configured on this laptop. <Link href="/auth/configuration" className="underline">View required settings.</Link></div>}
        <section className="mx-auto grid max-w-4xl gap-5 md:grid-cols-2">
          <article className="surface rounded-[28px] p-7 sm:p-8"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#ffbc90]/15 text-xl text-[#ffbc90]">✉</div><p className="eyebrow mt-8">Read-only workspace</p><h2 className="mt-3 text-2xl font-semibold">Continue as Analyst</h2><p className="mt-3 min-h-12 text-sm leading-6 text-[#bea99a]">Email one-time code through the Auth0 Passwordless Email connection.</p><a aria-disabled={!configured} href={configured ? `/auth/login?connection=${analystConnection}&returnTo=${encodeURIComponent(analystReturnTo)}` : "/auth/configuration"} className="mt-8 block rounded-xl bg-[#ffbc90] px-5 py-3.5 text-center text-sm font-semibold text-[#321b10]">Continue with email code →</a></article>
          <article className="rounded-[28px] border border-[#71c7ec]/25 bg-[linear-gradient(145deg,#352319,#211610)] p-7 shadow-[0_24px_80px_rgba(0,0,0,.28)] sm:p-8"><div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-[#71c7ec]/25 bg-[#71c7ec]/10 text-xl text-[#8ad6f5]">⌾</div><p className="mt-8 font-mono text-[10px] uppercase tracking-[.19em] text-[#71c7ec]">Restricted control plane</p><h2 className="mt-3 text-2xl font-semibold">Operator Secure Access</h2><ul className="mt-4 min-h-20 space-y-2 text-sm text-[#bea99a]"><li>Protected operator access</li><li>Password + authenticator verification</li><li>Full simulation control</li></ul><a aria-disabled={!configured} href={configured ? `/auth/login?connection=${operatorConnection}&prompt=login&returnTo=${encodeURIComponent(operatorReturnTo)}` : "/auth/configuration"} className="mt-8 block rounded-xl border border-[#71c7ec]/35 bg-[#71c7ec]/10 px-5 py-3.5 text-center text-sm font-semibold text-[#a9e4fb]">Enter secure access →</a></article>
        </section><Link href="/simulation" className="mx-auto mt-8 block w-fit text-xs text-[#bea99a] hover:text-white">← Return to public live view</Link></div>
    </main>
  );
}
