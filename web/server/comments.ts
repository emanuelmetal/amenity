/**
 * Anonymous comments (PLAN.md §7). SECURITY / PRIVACY CRITICAL.
 *
 * - Authors are shown only as "Vecino/a anónimo/a". The server stores
 *   author_key = HMAC(K, device_id), with K derived from SESSION_SECRET and the device id
 *   taken from the signed session (auth.ts), plus the access code's id (Mode B: whoever runs
 *   the database could tell which apartment's code posted; see "Cómo funciona").
 *   Neither an author's key nor their access_code_id ever leaves this module: responses carry
 *   `mine`. (The moderation log shows moderators' own admin code ids, to admins only.)
 * - Every write needs `Origin` equal to the site's origin (and JSON for bodies), on top of the
 *   SameSite=Lax cookie: other sites cannot post, report or moderate in a neighbour's name.
 * - 10 comments per device per day. Three reports from distinct devices hide a comment until
 *   a moderator (an `admin` access code) looks at it; after that, reports no longer hide it.
 *   Every hide/restore is logged in comment_moderation with the moderator's access code.
 */
import { Hono } from "hono";
import type { Context } from "hono";
import type { Env, SessionData } from "./env";

type Bindings = Env & { session: SessionData };
type C = Context<{ Bindings: Bindings }>;

export const MAX_BODY = 2000;
export const DAILY_LIMIT = 10;
export const REPORTS_TO_HIDE = 3;

/** entity_type -> how to check that the commented thing is published. */
const ENTITIES: Record<string, { table: string; numeric: boolean } | null> = {
  general: null,
  expense: { table: "expense_lines", numeric: true },
  ticket: { table: "tickets", numeric: true },
  article: { table: "reglamento_articles", numeric: true },
  acta: { table: "actas", numeric: true },
  observation: { table: "observations", numeric: false },
};

// Personal identifiers are refused outright (the site never publishes them, PLAN.md §8).
const PERSONAL_DATA = [
  /\b(?:20|23|24|27)[-. ]?\d{8}[-. ]?\d\b/, // CUIL of a person
  /\b\d{22}\b/, // CBU / CVU
  /\bD\.?\s?N\.?\s?I\.?\s*(?:n[°ºro.]*\s*)?:?\s*\d{1,2}\.?\d{3}\.?\d{3}\b/i,
];

export const comments = new Hono<{ Bindings: Bindings }>();

async function hmac(key: ArrayBuffer, msg: string): Promise<ArrayBuffer> {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return crypto.subtle.sign("HMAC", k, new TextEncoder().encode(msg));
}

/** HMAC(HMAC(SESSION_SECRET, label), device_id): not reversible to the device id, and only
 *  comparable by whoever holds SESSION_SECRET. */
export async function authorKey(secret: string, deviceId: string): Promise<string> {
  return keyedHash(secret, "comment-author-v1", deviceId);
}

/** HMAC(HMAC(secret, label), value) as hex: one derived key per purpose (comments, ask limits). */
export async function keyedHash(secret: string, label: string, value: string): Promise<string> {
  const derived = await hmac(new TextEncoder().encode(secret).buffer as ArrayBuffer, label);
  const mac = await hmac(derived, value);
  return [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const isAdmin = (c: C) => c.env.session.kind === "admin";

function noStore(res: Response): Response {
  res.headers.set("Cache-Control", "no-store");
  return res;
}

/** CSRF: writes must come from our own pages. */
comments.use("*", async (c, next) => {
  if (c.req.method !== "GET" && c.req.method !== "HEAD") {
    const origin = c.req.header("Origin");
    if (!origin || origin !== new URL(c.req.url).origin) return c.json({ error: "bad_origin" }, 403);
    if (c.req.method === "POST" && !(c.req.header("Content-Type") ?? "").startsWith("application/json")) {
      return c.json({ error: "bad_content_type" }, 415);
    }
  }
  await next();
  c.res = noStore(c.res);
});

function parseId(v: string | undefined): number | null {
  return v && /^\d{1,16}$/.test(v) ? Number(v) : null;
}

/** Validated (entity_type, entity_id) of a published item, or an error code. */
async function target(
  c: C,
  type: unknown,
  rawId: unknown,
): Promise<{ type: string; id: number | string | null } | { error: string }> {
  if (typeof type !== "string" || !Object.hasOwn(ENTITIES, type)) return { error: "bad_entity" };
  const spec = ENTITIES[type];
  if (!spec) return rawId == null || rawId === "" ? { type, id: null } : { error: "bad_entity" };
  const s = String(rawId ?? "");
  const id = spec.numeric ? parseId(s) : /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
  if (id === null) return { error: "bad_entity" };
  const row = await c.env.DB.prepare(`SELECT 1 AS ok FROM ${spec.table} WHERE id = ?1`).bind(id).first();
  return row ? { type, id } : { error: "not_found" };
}

const PUBLIC_COLS = (admin: boolean) =>
  `c.id, c.entity_type, c.entity_id, c.body, c.created_at, c.status${admin ? ", c.reports, c.moderated" : ""}`;

type Row = Record<string, unknown> & { mine: number };
const shape = <T extends Row>(rows: T[]) =>
  rows.map((r) => ({ ...r, author: "Vecino/a anónimo/a", mine: r.mine === 1 }) as Omit<T, "mine"> & {
    author: string;
    mine: boolean;
  });

comments.get("/comments", async (c) => {
  const t = await target(c, c.req.query("entity_type"), c.req.query("entity_id"));
  if ("error" in t) return c.json({ error: t.error }, t.error === "not_found" ? 404 : 400);
  const admin = isAdmin(c);
  const me = await authorKey(c.env.SESSION_SECRET, c.env.session.deviceId);
  const { results } = await c.env.DB.prepare(
    `SELECT ${PUBLIC_COLS(admin)}, (c.author_key = ?1) AS mine
     FROM comments c
     WHERE c.entity_type = ?2 AND c.entity_id IS ?3
       AND (c.status = 'visible' OR (?4 = 1 AND c.status = 'hidden'))
     ORDER BY c.created_at DESC, c.id DESC LIMIT 500`,
  )
    .bind(me, t.type, t.id, admin ? 1 : 0)
    .all<Row>();
  return c.json(shape(results).reverse()); // the newest 500, oldest first
});

/** Latest visible comments anywhere, with a label of what they are about. */
comments.get("/comments/recent", async (c) => {
  const me = await authorKey(c.env.SESSION_SECRET, c.env.session.deviceId);
  const { results } = await c.env.DB.prepare(
    `SELECT ${PUBLIC_COLS(false)}, (c.author_key = ?1) AS mine,
            CASE c.entity_type
              WHEN 'expense' THEN (SELECT e.concepto || ' · ' || e.period_id FROM expense_lines e WHERE e.id = c.entity_id)
              WHEN 'ticket' THEN (SELECT COALESCE(t.proveedor, 'Comprobante') FROM tickets t WHERE t.id = c.entity_id)
              WHEN 'article' THEN (SELECT 'Artículo ' || a.numero FROM reglamento_articles a WHERE a.id = c.entity_id)
              WHEN 'acta' THEN (SELECT COALESCE('Acta ' || a.numero, 'Acta') || ' · ' || a.fecha FROM actas a WHERE a.id = c.entity_id)
              WHEN 'observation' THEN (SELECT o.titulo FROM observations o WHERE o.id = c.entity_id)
            END AS label
     FROM comments c WHERE c.status = 'visible'
       AND (c.entity_type = 'general' OR label IS NOT NULL) -- what it is about is still published
     ORDER BY c.created_at DESC, c.id DESC LIMIT 50`,
  )
    .bind(me)
    .all<Row>();
  return c.json(shape(results));
});

comments.post("/comments", async (c) => {
  let input: { entity_type?: unknown; entity_id?: unknown; body?: unknown };
  try {
    input = await c.req.json();
  } catch {
    return c.json({ error: "bad_json" }, 400);
  }
  if (!input || typeof input !== "object") return c.json({ error: "bad_json" }, 400);
  const t = await target(c, input.entity_type, input.entity_id);
  if ("error" in t) return c.json({ error: t.error }, t.error === "not_found" ? 404 : 400);
  // eslint-disable-next-line no-control-regex
  const body = typeof input.body === "string" ? input.body.replace(/[\u0000-\u0009\u000B-\u001F\u007F]/g, "").trim() : "";
  if (!body || body.length > MAX_BODY) return c.json({ error: "bad_body", max: MAX_BODY }, 400);
  if (PERSONAL_DATA.some((re) => re.test(body))) return c.json({ error: "personal_data" }, 400);

  const key = await authorKey(c.env.SESSION_SECRET, c.env.session.deviceId);
  // One statement: the limit check and the insert cannot interleave with another request.
  // Per device on the shared link; per access code on unit/admin links (re-opening the
  // link gives a new device id, so per device would not limit anything there).
  const row = await c.env.DB.prepare(
    `INSERT INTO comments (entity_type, entity_id, body, author_key, access_code_id)
     SELECT ?1, ?2, ?3, ?4, ?5
     WHERE (SELECT count(*) FROM comments
            WHERE (CASE WHEN ?7 = 1 THEN author_key = ?4 ELSE access_code_id = ?5 END)
              AND created_at > datetime('now', '-1 day')) < ?6
     RETURNING id, entity_type, entity_id, body, created_at, status`,
  )
    .bind(t.type, t.id, body, key, c.env.session.codeId, DAILY_LIMIT, c.env.session.kind === "shared" ? 1 : 0)
    .first<Record<string, unknown>>();
  if (!row) return c.json({ error: "rate_limited", limit: DAILY_LIMIT }, 429);
  return c.json({ ...row, author: "Vecino/a anónimo/a", mine: true }, 201);
});

/** Authors can remove their own comment (it is kept as 'removed', never shown). */
comments.delete("/comments/:id", async (c) => {
  const id = parseId(c.req.param("id"));
  if (id === null) return c.json({ error: "not_found" }, 404);
  const key = await authorKey(c.env.SESSION_SECRET, c.env.session.deviceId);
  const row = await c.env.DB.prepare(
    "UPDATE comments SET status = 'removed' WHERE id = ?1 AND author_key = ?2 AND status != 'removed' RETURNING id",
  )
    .bind(id, key)
    .first();
  return row ? c.json({ ok: true }) : c.json({ error: "not_found" }, 404);
});

comments.post("/comments/:id/report", async (c) => {
  const id = parseId(c.req.param("id"));
  if (id === null) return c.json({ error: "not_found" }, 404);
  const key = await authorKey(c.env.SESSION_SECRET, c.env.session.deviceId);
  const found = await c.env.DB.prepare("SELECT author_key FROM comments WHERE id = ?1 AND status = 'visible'")
    .bind(id)
    .first<{ author_key: string }>();
  if (!found) return c.json({ error: "not_found" }, 404);
  if (found.author_key === key) return c.json({ ok: true }); // reporting oneself counts for nothing
  // Who reports: the device on the shared link; the access code on unit/admin links, so one
  // apartment opening its link in three windows still counts once (HMAC: no raw code id stored).
  const reporter =
    c.env.session.kind === "shared" ? key : await authorKey(c.env.SESSION_SECRET, `code:${c.env.session.codeId}`);
  await c.env.DB.prepare("INSERT OR IGNORE INTO comment_reports (comment_id, author_key) VALUES (?1, ?2)")
    .bind(id, reporter)
    .run();
  await c.env.DB.prepare(
    `UPDATE comments SET
       reports = (SELECT count(*) FROM comment_reports WHERE comment_id = ?1),
       status = CASE WHEN moderated = 0 AND status = 'visible'
                      AND (SELECT count(*) FROM comment_reports WHERE comment_id = ?1) >= ?2
                     THEN 'hidden' ELSE status END
     WHERE id = ?1`,
  )
    .bind(id, REPORTS_TO_HIDE)
    .run();
  return c.json({ ok: true });
});

// ---- Moderation (admin access codes only) ------------------------------------------

comments.post("/comments/:id/moderate", async (c) => {
  if (!isAdmin(c)) return c.json({ error: "forbidden" }, 403);
  const id = parseId(c.req.param("id"));
  let action: unknown;
  try {
    action = ((await c.req.json()) as { action?: unknown } | null)?.action;
  } catch {
    return c.json({ error: "bad_json" }, 400);
  }
  if (id === null || (action !== "hide" && action !== "restore")) return c.json({ error: "bad_request" }, 400);
  const row = await c.env.DB.prepare(
    `UPDATE comments SET status = ?2, moderated = 1 WHERE id = ?1 AND status != 'removed' RETURNING id`,
  )
    .bind(id, action === "hide" ? "hidden" : "visible")
    .first();
  if (!row) return c.json({ error: "not_found" }, 404);
  await c.env.DB.prepare("INSERT INTO comment_moderation (comment_id, action, access_code_id) VALUES (?1, ?2, ?3)")
    .bind(id, action, c.env.session.codeId)
    .run();
  return c.json({ ok: true });
});

/** Reported or hidden comments, with their moderation history. */
comments.get("/moderation", async (c) => {
  if (!isAdmin(c)) return c.json({ error: "forbidden" }, 403);
  const { results } = await c.env.DB.prepare(
    `SELECT ${PUBLIC_COLS(true)}, 0 AS mine,
            (SELECT json_group_array(json_object('action', m.action, 'moderator', m.access_code_id, 'at', m.created_at))
               FROM (SELECT * FROM comment_moderation m WHERE m.comment_id = c.id ORDER BY m.created_at, m.id) m) AS history
     FROM comments c
     WHERE c.status != 'removed' -- deleted by its author: not shown to anyone
       AND (c.status = 'hidden' OR c.reports > 0 OR EXISTS (SELECT 1 FROM comment_moderation m WHERE m.comment_id = c.id))
     ORDER BY c.status = 'hidden' DESC, c.reports DESC, c.created_at DESC LIMIT 200`,
  ).all<Row & { history: string }>();
  return c.json(shape(results).map((r) => ({ ...r, history: JSON.parse(String(r.history)) as unknown[] })));
});
