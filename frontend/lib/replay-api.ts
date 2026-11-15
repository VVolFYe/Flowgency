import { NextResponse } from "next/server";
import { auth0, auth0Configured } from "@/lib/auth0";

const BACKEND_URL = (
  process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

export async function proxyReplayRequest(path: string, request: Request) {
  if (!auth0Configured()) {
    return NextResponse.json(
      { detail: "Auth0 is not configured on the Next.js server" },
      { status: 503 },
    );
  }
  let token: string;
  try {
    const session = await auth0.getSession();
    if (!session) {
      return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
    }
    token = (await auth0.getAccessToken()).token;
  } catch {
    return NextResponse.json(
      { detail: "Your Auth0 session or access token expired. Sign in again." },
      { status: 401 },
    );
  }

  const range = request.headers.get("range");
  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      headers: {
        Authorization: `Bearer ${token}`,
        ...(range ? { Range: range } : {}),
      },
      cache: "no-store",
    });
    const headers = new Headers();
    for (const name of [
      "accept-ranges",
      "cache-control",
      "content-disposition",
      "content-length",
      "content-range",
      "content-type",
    ]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(response.body, { status: response.status, headers });
  } catch {
    return NextResponse.json(
      { detail: `Cannot reach the Flowgency backend at ${BACKEND_URL}` },
      { status: 503 },
    );
  }
}
