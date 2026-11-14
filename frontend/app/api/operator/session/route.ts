import { NextResponse } from "next/server";
import {
  createOperatorSession,
  OPERATOR_SESSION_COOKIE,
  operatorAuthConfigured,
  operatorSessionCookieOptions,
  validateOperatorCredentials,
} from "@/lib/operator-auth";

export async function POST(request: Request) {
  if (!operatorAuthConfigured()) {
    return NextResponse.json({ error: "Operator authentication is not configured on the server." }, { status: 503 });
  }
  let credentials: { username?: unknown; password?: unknown };
  try {
    credentials = await request.json() as { username?: unknown; password?: unknown };
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  if (typeof credentials.username !== "string" || typeof credentials.password !== "string" || !validateOperatorCredentials(credentials.username, credentials.password)) {
    return NextResponse.json({ error: "Invalid Operator credentials." }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(OPERATOR_SESSION_COOKIE, await createOperatorSession(credentials.username), operatorSessionCookieOptions);
  return response;
}
