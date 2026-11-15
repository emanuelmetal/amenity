/** Read-only JSON API (Phase 1). Every route runs behind `gate()` in worker.ts. */
import { Hono } from "hono";
import type { Env, SessionData } from "./env";

type Bindings = Env & { session: SessionData };

export const api = new Hono<{ Bindings: Bindings }>().basePath("/api");

const PAGE_SIZE = 50;

/** Turns free text into a safe FTS5 query: each word quoted, last one as prefix. */
export function toFtsQuery(q: string): string | null {
  const words = q
    .normalize("NFC")
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w.length > 0)
    .slice(0, 8);
  if (words.length === 0) return null;
  return words.map((w, i) => `"${w}"${i === words.length - 1 ? "*" : ""}`).join(" ");
}

function intParam(v: string | undefined): number | null {
  if (v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

api.get("/me", (c) => c.json({ kind: c.env.session.kind }));

api.get("/periods", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT p.id, p.total, p.document_id,
            (SELECT COALESCE(SUM(importe),0) FROM expense_lines e WHERE e.period_id = p.id) AS lines_total,
            (SELECT COUNT(*) FROM expense_lines e WHERE e.period_id = p.id) AS lines
     FROM periods p ORDER BY p.id DESC`,
  ).all();
  return c.json(results);
});

api.get("/rubros", async (c) => {
  const { results } = await c.env.DB.prepare(
    "SELECT rubro, COUNT(*) AS lines, SUM(importe) AS total FROM expense_lines GROUP BY rubro ORDER BY rubro",
  ).all();
  return c.json(results);
});

const SORTS: Record<string, string> = {
  period: "e.period_id",
  rubro: "e.rubro",
  concepto: "e.concepto",
  proveedor: "e.proveedor",
  categoria: "e.subcategoria",
  importe: "e.importe",
};

api.get("/expenses", async (c) => {
  const q = c.req.query();
  const where: string[] = [];
  const args: unknown[] = [];
  const add = (sql: string, v: unknown) => {
    args.push(v);
    where.push(sql.replace("?", `?${args.length}`));
  };
  if (q.period) add("e.period_id = ?", q.period);
  if (q.rubro) add("e.rubro = ?", q.rubro);
  const min = intParam(q.min);
  const max = intParam(q.max);
  if (min !== null) add("e.importe >= ?", min);
  if (max !== null) add("e.importe <= ?", max);
  if (q.q) {
    const like = `%${q.q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`;
    args.push(like);
    const n = args.length;
    where.push(
      `(e.concepto LIKE ?${n} ESCAPE '\\' OR e.detalle LIKE ?${n} ESCAPE '\\' OR e.proveedor LIKE ?${n} ESCAPE '\\' OR e.subcategoria LIKE ?${n} ESCAPE '\\')`,
    );
  }
  const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
  const sortCol = SORTS[q.sort ?? ""] ?? "e.period_id";
  const dir = q.dir === "asc" ? "ASC" : "DESC";
  const page = Math.min(10_000, Math.max(1, Math.floor(intParam(q.page) ?? 1)));
  const offset = (page - 1) * PAGE_SIZE;

  const [rows, agg] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT e.id, e.period_id, e.rubro, e.subcategoria, e.concepto, e.detalle, e.proveedor, e.importe,
              CASE WHEN pg.restricted = 0 THEN e.page_id END AS page_id, e.confidence, e.verified
       FROM expense_lines e LEFT JOIN pages pg ON pg.id = e.page_id ${whereSql}
       ORDER BY ${sortCol} ${dir}, e.id ASC
       LIMIT ${PAGE_SIZE} OFFSET ${offset}`,
    ).bind(...args),
    c.env.DB.prepare(
      `SELECT COUNT(*) AS count, COALESCE(SUM(e.importe),0) AS total FROM expense_lines e ${whereSql}`,
    ).bind(...args),
  ]);
  const a = (agg.results[0] ?? { count: 0, total: 0 }) as { count: number; total: number };
  return c.json({ rows: rows.results, count: a.count, total: a.total, page, pageSize: PAGE_SIZE });
});

api.get("/expenses/:id", async (c) => {
  const row = await c.env.DB.prepare(
    `SELECT e.id, e.period_id, e.rubro, e.subcategoria, e.concepto, e.detalle, e.proveedor, e.importe,
            e.confidence, e.verified, pg.id AS page_id, d.id AS document_id, pg.page_no
     FROM expense_lines e
     LEFT JOIN pages pg ON pg.id = e.page_id AND pg.restricted = 0
     LEFT JOIN documents d ON d.id = pg.document_id
     WHERE e.id = ?1`,
  )
    .bind(c.req.param("id"))
    .first();
  if (!row) return c.json({ error: "not_found" }, 404);
  return c.json(row);
});

api.get("/reglamento", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT a.id, a.numero, a.titulo, a.verified, a.document_id, d.title AS document_title
     FROM reglamento_articles a LEFT JOIN documents d ON d.id = a.document_id
     ORDER BY d.title, a.orden`,
  ).all();
  return c.json(results);
});

api.get("/reglamento/:id", async (c) => {
  const row = await c.env.DB.prepare(
    `SELECT a.id, a.numero, a.orden, a.titulo, a.texto, a.page_ids_json, a.verified, a.document_id,
            d.title AS document_title
     FROM reglamento_articles a LEFT JOIN documents d ON d.id = a.document_id WHERE a.id = ?1`,
  )
    .bind(c.req.param("id"))
    .first<{ page_ids_json: string } & Record<string, unknown>>();
  if (!row) return c.json({ error: "not_found" }, 404);
  const ids = (JSON.parse(row.page_ids_json) as number[]).filter(Number.isInteger);
  let pages: unknown[] = [];
  if (ids.length) {
    const placeholders = ids.map((_, i) => `?${i + 1}`).join(",");
    pages = (
      await c.env.DB.prepare(
        `SELECT id, document_id, page_no FROM pages WHERE restricted = 0 AND id IN (${placeholders}) ORDER BY page_no`,
      )
        .bind(...ids)
        .all()
    ).results;
  }
  const { page_ids_json: _drop, ...rest } = row;
  return c.json({ ...rest, pages });
});

api.get("/search", async (c) => {
  const fts = toFtsQuery(c.req.query("q") ?? "");
  if (!fts) return c.json([]);
  // \u0002 / \u0003 mark hits; the client renders them as <mark> without innerHTML.
  const { results } = await c.env.DB.prepare(
    `SELECT s.entity_type, s.entity_id, s.page_id, s.title,
            snippet(search_fts, 4, char(2), char(3), '…', 16) AS snippet,
            pg.document_id, pg.page_no
     FROM search_fts s
     LEFT JOIN pages pg ON pg.id = s.page_id
     WHERE search_fts MATCH ?1 AND (s.page_id IS NULL OR pg.restricted = 0)
     ORDER BY rank LIMIT 40`,
  )
    .bind(fts)
    .all();
  return c.json(results);
});

api.get("/documents", async (c) => {
  const { results } = await c.env.DB.prepare(
    "SELECT id, kind, period, title, pages FROM documents ORDER BY kind, period DESC, id",
  ).all();
  return c.json(results);
});

api.get("/pages/:id", async (c) => {
  const page = await c.env.DB.prepare(
    `SELECT pg.id, pg.document_id, pg.page_no, pg.text, pg.ocr_engine,
            d.title AS document_title, d.kind AS document_kind, d.period, d.pages AS document_pages
     FROM pages pg JOIN documents d ON d.id = pg.document_id
     WHERE pg.id = ?1 AND pg.restricted = 0`,
  )
    .bind(c.req.param("id"))
    .first<{ document_id: number; page_no: number } & Record<string, unknown>>();
  if (!page) return c.json({ error: "not_found" }, 404);
  const { results } = await c.env.DB.prepare(
    `SELECT id, page_no FROM pages WHERE document_id = ?1 AND restricted = 0
       AND page_no IN (?2, ?3)`,
  )
    .bind(page.document_id, page.page_no - 1, page.page_no + 1)
    .all<{ id: number; page_no: number }>();
  return c.json({
    ...page,
    prev_id: results.find((r) => r.page_no === page.page_no - 1)?.id ?? null,
    next_id: results.find((r) => r.page_no === page.page_no + 1)?.id ?? null,
  });
});

async function streamObject(env: Env, key: string, contentType: string, filename?: string): Promise<Response> {
  const obj = await env.FILES.get(key);
  if (!obj) return Response.json({ error: "not_found" }, { status: 404 });
  const headers = new Headers({
    "Content-Type": contentType,
    "Cache-Control": "private, no-cache", // revalidate: revoked sessions/restricted pages must not keep reading
  });
  if (filename) headers.set("Content-Disposition", `inline; filename="${filename.replace(/[^\w.-]/g, "_")}"`);
  return new Response(obj.body as unknown as ReadableStream, { headers });
}

api.get("/files/page/:id", async (c) => {
  const row = await c.env.DB.prepare("SELECT r2_key_img FROM pages WHERE id = ?1 AND restricted = 0")
    .bind(c.req.param("id"))
    .first<{ r2_key_img: string }>();
  if (!row) return c.json({ error: "not_found" }, 404);
  return streamObject(c.env, row.r2_key_img, "image/webp");
});

api.get("/files/doc/:id", async (c) => {
  // r2_key_pdf always points at the published copy, in which restricted pages are blanked.
  const row = await c.env.DB.prepare("SELECT r2_key_pdf, title FROM documents WHERE id = ?1")
    .bind(c.req.param("id"))
    .first<{ r2_key_pdf: string; title: string }>();
  if (!row) return c.json({ error: "not_found" }, 404);
  return streamObject(c.env, row.r2_key_pdf, "application/pdf", `${row.title}.pdf`);
});

api.all("*", (c) => c.json({ error: "not_found" }, 404));
