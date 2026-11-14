export const OPERATOR_SESSION_COOKIE = "flowgency_operator_session";
const SESSION_DURATION_SECONDS = 8 * 60 * 60;

interface SessionPayload {
  role: "Operator";
  username: string;
  expiresAt: number;
}

const encoder = new TextEncoder();

function toBase64Url(value: string) {
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function fromBase64Url(value: string) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return atob(padded);
}

async function signature(payload: string, secret: string) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const bytes = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
  let binary = "";
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return toBase64Url(binary);
}

function equalConstantTime(left: string, right: string) {
  const length = Math.max(left.length, right.length);
  let difference = left.length ^ right.length;
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

export function operatorAuthConfigured() {
  return Boolean(process.env.OPERATOR_USERNAME && process.env.OPERATOR_PASSWORD && process.env.OPERATOR_SESSION_SECRET);
}

export function validateOperatorCredentials(username: string, password: string) {
  const expectedUsername = process.env.OPERATOR_USERNAME;
  const expectedPassword = process.env.OPERATOR_PASSWORD;
  if (!expectedUsername || !expectedPassword) return false;
  return equalConstantTime(username, expectedUsername) && equalConstantTime(password, expectedPassword);
}

export async function createOperatorSession(username: string) {
  const secret = process.env.OPERATOR_SESSION_SECRET;
  if (!secret) throw new Error("Operator authentication is not configured");
  const payload: SessionPayload = {
    role: "Operator",
    username,
    expiresAt: Math.floor(Date.now() / 1000) + SESSION_DURATION_SECONDS,
  };
  const encoded = toBase64Url(JSON.stringify(payload));
  return `${encoded}.${await signature(encoded, secret)}`;
}

export async function verifyOperatorSession(token: string | undefined | null): Promise<SessionPayload | null> {
  const secret = process.env.OPERATOR_SESSION_SECRET;
  if (!token || !secret) return null;
  const [encoded, suppliedSignature, extra] = token.split(".");
  if (!encoded || !suppliedSignature || extra) return null;
  const expectedSignature = await signature(encoded, secret);
  if (!equalConstantTime(suppliedSignature, expectedSignature)) return null;
  try {
    const payload = JSON.parse(fromBase64Url(encoded)) as SessionPayload;
    if (payload.role !== "Operator" || typeof payload.username !== "string" || payload.expiresAt <= Date.now() / 1000) return null;
    return payload;
  } catch {
    return null;
  }
}

export const operatorSessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: SESSION_DURATION_SECONDS,
};
