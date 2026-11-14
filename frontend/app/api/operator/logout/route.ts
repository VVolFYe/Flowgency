import { NextResponse } from "next/server";
import { OPERATOR_SESSION_COOKIE } from "@/lib/operator-auth";

export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(OPERATOR_SESSION_COOKIE, "", { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
  return response;
}
