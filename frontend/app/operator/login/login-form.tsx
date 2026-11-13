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
    <form action={submit} className="mt-8 space-y-4">
      <div><label htmlFor="username" className="text-xs text-[#8c9ba4]">Username</label><input id="username" name="username" autoComplete="username" required className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-4 py-3 text-sm outline-none transition focus:border-[#72e9a6]/60" /></div>
      <div><label htmlFor="password" className="text-xs text-[#8c9ba4]">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required className="mt-2 w-full rounded-xl border border-white/10 bg-[#0b1115] px-4 py-3 text-sm outline-none transition focus:border-[#72e9a6]/60" /></div>
      {error && <p role="alert" className="rounded-xl border border-[#ff6670]/25 bg-[#ff6670]/10 px-3 py-2 text-sm text-[#ffabb1]">{error}</p>}
      <button type="submit" disabled={pending} className="w-full rounded-xl bg-[#72e9a6] px-4 py-3 text-sm font-semibold text-[#06130c] transition hover:bg-[#91f7bf] disabled:opacity-50">{pending ? "Signing in…" : "Enter Operator workspace"}</button>
    </form>
  );
}
