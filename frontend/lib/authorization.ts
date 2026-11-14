import { redirect } from "next/navigation";
import { auth0, auth0Configured } from "./auth0";

export const permissions = {
  simulationRead: "simulation:read",
  analyticsRead: "analytics:read",
  simulationControl: "simulation:control",
} as const;

function decodePermissions(token: string): Set<string> {
  const payload = token.split(".")[1];
  if (!payload) return new Set();
  try {
    const normalized = payload.replaceAll("-", "+").replaceAll("_", "/");
    const claims = JSON.parse(Buffer.from(normalized, "base64").toString("utf8")) as { permissions?: unknown };
    return new Set(Array.isArray(claims.permissions) ? claims.permissions.filter((item): item is string => typeof item === "string") : []);
  } catch {
    return new Set();
  }
}

export async function getAuthorization() {
  if (!auth0Configured()) return { configured: false as const, authenticated: false as const, permissions: new Set<string>() };
  let session;
  try {
    session = await auth0.getSession();
  } catch {
    return { configured: true as const, authenticated: false as const, permissions: new Set<string>(), sessionError: true as const };
  }
  if (!session) return { configured: true as const, authenticated: false as const, permissions: new Set<string>() };
  try {
    const { token } = await auth0.getAccessToken();
    return { configured: true as const, authenticated: true as const, permissions: decodePermissions(token), user: session.user };
  } catch {
    return { configured: true as const, authenticated: true as const, permissions: new Set<string>(), user: session.user, tokenError: true as const };
  }
}

export async function requirePermissions(required: string[], returnTo: string) {
  const authorization = await getAuthorization();
  if (!authorization.configured) redirect("/auth/configuration");
  if ("sessionError" in authorization && authorization.sessionError) redirect("/auth/error?code=session_invalid");
  if (!authorization.authenticated) redirect(`/access?next=${encodeURIComponent(returnTo)}`);
  if ("tokenError" in authorization && authorization.tokenError) redirect("/auth/session-expired");
  const granted = required.every((permission) => authorization.permissions.has(permission));
  if (!granted) {
    const hasAnyFlowgencyPermission = authorization.permissions.size > 0;
    redirect(hasAnyFlowgencyPermission ? "/access-denied" : "/access-pending");
  }
  return authorization;
}
