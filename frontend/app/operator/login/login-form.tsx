"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (formData: FormData) => {
    setPending(true);
    setError(null);
    const response = await fetch("/api/operator/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: formData.get("username"), password: formData.get("password") }),
    }).catch(() => null);
    if (!response) {
      setError("Could not reach the Next.js server.");
      setPending(false);
      return;
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({ error: "Login failed." })) as { error?: string };
      setError(body.error ?? "Login failed.");
      setPending(false);
      return;
    }
    const requested = searchParams.get("next");
    const destination = requested?.startsWith("/operator") && !requested.startsWith("//") ? requested : "/operator";
    router.replace(destination);
    router.refresh();
  };

  return (
    <form action={submit} className="mt-8 space-y-5">
      <div><label htmlFor="username" className="text-xs font-medium text-[#a0adb3]">Username</label><input id="username" name="username" autoComplete="username" required className="mt-2 w-full rounded-xl border border-white/10 bg-[#090e11] px-4 py-3.5 text-sm text-white outline-none transition placeholder:text-[#52616a] hover:border-white/20 focus:border-[#7cf2ad]/70" /></div>
      <div><label htmlFor="password" className="text-xs font-medium text-[#a0adb3]">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required className="mt-2 w-full rounded-xl border border-white/10 bg-[#090e11] px-4 py-3.5 text-sm text-white outline-none transition placeholder:text-[#52616a] hover:border-white/20 focus:border-[#7cf2ad]/70" /></div>
      {error && <p role="alert" className="rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-3 py-2 text-sm text-[#ffabb1]">{error}</p>}
      <button type="submit" disabled={pending} className="w-full rounded-xl bg-[#7cf2ad] px-4 py-3.5 text-sm font-semibold text-[#07140c] transition hover:-translate-y-0.5 hover:bg-[#98f7be] disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50">{pending ? "Signing in…" : "Enter Operator workspace →"}</button>
    </form>
  );
}
