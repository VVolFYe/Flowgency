import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { auth0, auth0Configured } from "@/lib/auth0";

export async function proxy(request: NextRequest) {
  if (!auth0Configured() && request.nextUrl.pathname.startsWith("/auth/")) {
    return NextResponse.redirect(new URL("/auth/configuration", request.url));
  }
  if (request.nextUrl.pathname === "/analytics") {
    return NextResponse.redirect(new URL("/operator/benchmarks", request.url));
  }
  return auth0.middleware(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"],
};
