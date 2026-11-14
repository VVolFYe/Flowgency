import { NextResponse } from "next/server";
import { auth0, auth0Configured } from "@/lib/auth0";

const COMMANDS = new Set(["start", "pause", "resume", "reset", "stop", "speed"]);
const BACKEND_URL = (process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export async function POST(request: Request, { params }: { params: Promise<{ command: string }> }) {
  const { command } = await params;
  if (!COMMANDS.has(command)) return NextResponse.json({ detail: "Unknown simulation command" }, { status: 404 });
  if (!auth0Configured()) return NextResponse.json({ detail: "Auth0 is not configured on the Next.js server" }, { status: 503 });

  let token: string;
  try {
    const session = await auth0.getSession();
    if (!session) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
    token = (await auth0.getAccessToken()).token;
  } catch {
    return NextResponse.json({ detail: "Your Auth0 session or access token expired. Sign in again." }, { status: 401 });
  }

  let body: string | undefined;
  try {
    body = request.headers.get("content-length") === "0" ? undefined : await request.text();
    if (body === "") body = undefined;
  } catch {
    return NextResponse.json({ detail: "Invalid command body" }, { status: 400 });
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/simulation/${command}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const responseBody = await response.text();
    return new NextResponse(responseBody, { status: response.status, headers: { "Content-Type": response.headers.get("content-type") || "application/json" } });
  } catch {
    return NextResponse.json({ detail: `Cannot reach the Flowgency backend at ${BACKEND_URL}` }, { status: 503 });
  }
}
