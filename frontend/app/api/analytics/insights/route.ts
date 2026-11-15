import { NextResponse } from "next/server";
import { auth0, auth0Configured } from "@/lib/auth0";

const BACKEND_URL = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

/** Same-origin proxy for the Gemini AI review: adds the Auth0 access token (analytics:read) server-side. */
export async function POST(request: Request) {
  if (!auth0Configured()) return NextResponse.json({ detail: "Auth0 is not configured on the Next.js server" }, { status: 503 });

  let token: string;
  try {
    const session = await auth0.getSession();
    if (!session) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
    token = (await auth0.getAccessToken()).token;
  } catch {
    return NextResponse.json({ detail: "Your Auth0 session or access token expired. Sign in again." }, { status: 401 });
  }

  // Forward only the dataset selector; statistics are always read by the backend.
  let entryId: string | null;
  try {
    const body = (await request.json()) as { entry_id?: unknown };
    if (body.entry_id !== null && body.entry_id !== undefined && typeof body.entry_id !== "string") throw new Error();
    entryId = typeof body.entry_id === "string" ? body.entry_id : null;
  } catch {
    return NextResponse.json({ detail: "Invalid insights request body" }, { status: 400 });
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/analytics/insights`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ entry_id: entryId }),
      cache: "no-store",
      signal: AbortSignal.timeout(30000),
    });
    const responseBody = await response.text();
    return new NextResponse(responseBody, { status: response.status, headers: { "Content-Type": response.headers.get("content-type") || "application/json" } });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      return NextResponse.json({ detail: "The AI review timed out. Try again." }, { status: 504 });
    }
    return NextResponse.json({ detail: `Cannot reach the Flowgency backend at ${BACKEND_URL}` }, { status: 503 });
  }
}
