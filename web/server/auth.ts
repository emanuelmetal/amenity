/**
 * Access-link authentication (PLAN.md §3). SECURITY CRITICAL.
 *
 * - GET /acceso?k=<token>: look up sha256(token) in access_codes, set a signed
 *   session cookie and redirect to "/" so the token leaves the URL bar.
 * - Every other request (static assets, API, files) needs a valid cookie whose
 *   access code is still active.
 */
import { sign, verify } from "hono/jwt";
import type { CodeKind, Env, SessionData } from "./env";

export const COOKIE_NAME = "t3s";
export const SESSION_DAYS = 180;
export const RATE_LIMIT_PER_HOUR = 10;

const SECURITY_HEADERS: Record<string, string> = {
  "X-Robots-Tag": "noindex, nofollow",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Strict-Transport-Security": "max-age=31536000",
};

// No inline scripts anywhere (Vite emits module files); inline styles are used by
// React style props and the access page. Not applied to PDFs: it can break the
// browser's built-in PDF viewer.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; " +
  "frame-ancestors 'none'";

export async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function randomId(bytes = 16): string {
  const a = crypto.getRandomValues(new Uint8Array(bytes));
  return btoa(String.fromCharCode(...a)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function withSecurityHeaders(res: Response): Response {
  // Responses from fetch()/ASSETS may have immutable headers; copy to be safe.
  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) out.headers.set(k, v);
  if (!out.headers.get("Content-Type")?.startsWith("application/pdf")) {
    out.headers.set("Content-Security-Policy", CSP);
  }
  return out;
}

function readCookie(request: Request, name: string): string | null {
  const header = request.headers.get("Cookie");
  if (!header) return null;
  for (const part of header.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return rest.join("=");
  }
  return null;
}

const DENIED_HTML = `<!doctype html>
<html lang="es-AR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Torre 3 · Acceso</title>
<style>body{font-family:ui-sans-serif,system-ui,sans-serif;background:#fafafa;color:#717680;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}
main{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:24px;max-width:420px}h1{color:#171717;font-size:20px;margin:0 0 8px}</style></head>
<body><main><h1>Portal de vecinos · Torre 3</h1>
<p>Este sitio es privado. Pedí el enlace de acceso a la comisión.</p></main></body></html>`;

function denied(request: Request): Response {
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  return new Response(DENIED_HTML, {
    status: 401,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

/**
 * Rate limit on FAILED attempts only: neighbours behind one carrier IP (CGNAT)
 * opening a valid link must never lock each other out; 256-bit tokens make
 * guessing infeasible anyway, the limit just stops noisy scanning.
 */
async function attemptBucket(env: Env, request: Request, now: number) {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  return { ipHash: await sha256Hex(`${env.SESSION_SECRET}:${ip}`), windowStart: now - (now % 3600) };
}

async function tooManyFailures(env: Env, b: { ipHash: string; windowStart: number }): Promise<boolean> {
  const row = await env.DB.prepare("SELECT count FROM access_attempts WHERE ip_hash = ?1 AND window_start = ?2")
    .bind(b.ipHash, b.windowStart)
    .first<{ count: number }>();
  return (row?.count ?? 0) >= RATE_LIMIT_PER_HOUR;
}

async function recordFailure(env: Env, b: { ipHash: string; windowStart: number }): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO access_attempts (ip_hash, window_start, count) VALUES (?1, ?2, 1)
     ON CONFLICT (ip_hash, window_start) DO UPDATE SET count = count + 1`,
  )
    .bind(b.ipHash, b.windowStart)
    .run();
  // Opportunistic cleanup of old buckets.
  await env.DB.prepare("DELETE FROM access_attempts WHERE window_start < ?1").bind(b.windowStart - 86400).run();
}

interface CodeRow {
  id: number;
  kind: CodeKind;
}

async function findActiveCode(env: Env, where: "hash" | "id", value: string | number): Promise<CodeRow | null> {
  const col = where === "hash" ? "code_hash" : "id";
  return env.DB.prepare(
    `SELECT id, kind FROM access_codes
     WHERE ${col} = ?1 AND active = 1 AND (expires_at IS NULL OR expires_at > datetime('now'))`,
  )
    .bind(value)
    .first<CodeRow>();
}

async function handleAccessLink(request: Request, env: Env, now: number): Promise<Response> {
  const bucket = await attemptBucket(env, request, now);
  const token = new URL(request.url).searchParams.get("k") ?? "";
  // Tokens are 32 random bytes in base64url (43 chars). Reject anything implausible early.
  // A valid token always works: the limit only applies to failures (truncated links from a
  // shared carrier IP must not lock out neighbours who have the right link).
  const code = /^[A-Za-z0-9_-]{32,128}$/.test(token) ? await findActiveCode(env, "hash", await sha256Hex(token)) : null;
  if (!code) {
    if (await tooManyFailures(env, bucket)) {
      return new Response("Demasiados intentos. Probá de nuevo en una hora.", {
        status: 429,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Retry-After": "3600" },
      });
    }
    await recordFailure(env, bucket);
    return denied(request);
  }

  await env.DB.prepare(
    "UPDATE access_codes SET last_used_at = datetime('now'), uses = uses + 1 WHERE id = ?1",
  )
    .bind(code.id)
    .run();

  const exp = now + SESSION_DAYS * 86400;
  const jwt = await sign({ cid: code.id, kind: code.kind, did: randomId(), iat: now, exp }, env.SESSION_SECRET, "HS256");
  const cookie = `${COOKIE_NAME}=${jwt}; Path=/; Max-Age=${SESSION_DAYS * 86400}; HttpOnly; Secure; SameSite=Lax`;
  return new Response(null, {
    status: 302,
    headers: { Location: "/", "Set-Cookie": cookie, "Cache-Control": "no-store" },
  });
}

/** Verifies the session cookie and that its access code is still active. */
export async function readSession(request: Request, env: Env): Promise<SessionData | null> {
  const token = readCookie(request, COOKIE_NAME);
  if (!token) return null;
  let payload: Record<string, unknown>;
  try {
    payload = (await verify(token, env.SESSION_SECRET, "HS256")) as Record<string, unknown>;
  } catch {
    return null;
  }
  const cid = payload.cid;
  const did = payload.did;
  if (typeof cid !== "number" || typeof did !== "string") return null;
  const code = await findActiveCode(env, "id", cid);
  if (!code) return null; // revoked or expired code: session ends immediately
  return { codeId: code.id, kind: code.kind, deviceId: did };
}

/**
 * The whole gate. `next` serves the request (static asset or API) once the
 * session is known; the session is passed to it.
 */
export async function gate(
  request: Request,
  env: Env,
  next: (session: SessionData) => Promise<Response>,
  now: number = Math.floor(Date.now() / 1000),
): Promise<Response> {
  if (!env.SESSION_SECRET || env.SESSION_SECRET.length < 32) {
    return withSecurityHeaders(new Response("SESSION_SECRET not configured", { status: 500 }));
  }
  const url = new URL(request.url);
  if (url.pathname === "/acceso" || url.pathname === "/acceso/") {
    return withSecurityHeaders(await handleAccessLink(request, env, now));
  }
  const session = await readSession(request, env);
  if (!session) return withSecurityHeaders(denied(request));
  return withSecurityHeaders(await next(session));
}
