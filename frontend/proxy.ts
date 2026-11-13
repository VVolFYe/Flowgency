import { NextResponse, type NextRequest } from "next/server";
import { OPERATOR_SESSION_COOKIE, verifyOperatorSession } from "@/lib/operator-auth";

export async function proxy(request: NextRequest) {
  if (request.nextUrl.pathname === "/operator/login") return NextResponse.next();
  const session = await verifyOperatorSession(request.cookies.get(OPERATOR_SESSION_COOKIE)?.value);
  if (session) return NextResponse.next();
  const login = new URL("/operator/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/operator/:path*"],
};
