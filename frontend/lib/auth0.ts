import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { NextResponse } from "next/server";

const REQUIRED_AUTH0_ENV = [
  "AUTH0_DOMAIN",
  "AUTH0_CLIENT_ID",
  "AUTH0_CLIENT_SECRET",
  "AUTH0_SECRET",
  "APP_BASE_URL",
  "AUTH0_AUDIENCE",
] as const;

export function missingAuth0Configuration() {
  return REQUIRED_AUTH0_ENV.filter((name) => !process.env[name]);
}

export function auth0Configured() {
  return missingAuth0Configuration().length === 0;
}

// Harmless build-time values let public pages render before a teammate creates
// .env.local. Protected/auth routes reject missing configuration explicitly.
export const auth0 = new Auth0Client({
  domain: process.env.AUTH0_DOMAIN || "configuration-required.invalid",
  clientId: process.env.AUTH0_CLIENT_ID || "configuration-required",
  clientSecret: process.env.AUTH0_CLIENT_SECRET || "configuration-required",
  secret: process.env.AUTH0_SECRET || "0".repeat(64),
  appBaseUrl: process.env.APP_BASE_URL || "http://localhost:3000",
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE || "https://flowgency.invalid/api",
    scope: "openid profile email offline_access",
  },
  onCallback: async (error, context) => {
    const baseUrl = context.appBaseUrl || process.env.APP_BASE_URL || "http://localhost:3000";
    if (error) return NextResponse.redirect(new URL("/auth/error?code=callback_failed", baseUrl));
    return NextResponse.redirect(new URL(context.returnTo || "/access", baseUrl));
  },
  enableAccessTokenEndpoint: false,
});
