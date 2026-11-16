/** Read-only JSON API (Phase 1). Every route runs behind `gate()` in worker.ts. */
import { Hono } from "hono";
import type { Env, SessionData } from "./env";

type Bindings = Env & { session: SessionData };

export const api = new Hono<{ Bindings: Bindings }>().basePath("/api");

const PAGE_SIZE = 50;
const MAX_FILTER_VALUES = 100; // bounds the number of SQL parameters per filter
/** A link counts as "has a receipt" when a human confirmed it or the match is confident;
 *  "posible coincidencia" links (score < 0.9) are shown but not counted as coverage. */
const COVERED = "(l.status = 'verified' OR (l.status = 'auto' AND l.score >= 0.9))";
/** A line is backed by a covered receipt link or by a covered bank payment (same rule). */
const BACKED = (line: string) =>
  `(EXISTS (SELECT 1 FROM expense_ticket_links l WHERE l.expense_line_id = ${line} AND ${COVERED})
    OR EXISTS (SELECT 1 FROM expense_payment_links l WHERE l.expense_line_id = ${line} AND ${COVERED}))`;
/** Periods with uploaded evidence (receipts or a bank statement): only there "sin comprobante" means something. */
const EVIDENCE_PERIODS =
  "SELECT period_id FROM tickets WHERE period_id IS NOT NULL UNION SELECT period_id FROM bank_movements";

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
  // Multi-value filters: ?period=2026-01&period=2026-02 (repeated, never comma-split: rubros may contain commas).
  const addIn = (col: string, values: string[] | undefined) => {
    const vs = [...new Set((values ?? []).filter(Boolean))].slice(0, MAX_FILTER_VALUES);
    if (!vs.length) return;
    const ph = vs.map((v) => {
      args.push(v);
      return `?${args.length}`;
    });
    where.push(`${col} IN (${ph.join(",")})`);
  };
  addIn("e.period_id", c.req.queries("period"));
  addIn("e.rubro", c.req.queries("rubro"));
  if (q.sin_comprobante === "1") {
    // Only meaningful for periods whose receipts were uploaded; the client says so.
    where.push(`NOT ${BACKED("e.id")}`);
  }
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
              CASE WHEN pg.restricted = 0 THEN e.page_id END AS page_id, e.confidence, e.verified,
              (SELECT COUNT(*) FROM expense_ticket_links l WHERE l.expense_line_id = e.id AND l.status != 'rejected') AS tickets,
              (SELECT COUNT(*) FROM expense_payment_links l WHERE l.expense_line_id = e.id AND l.status != 'rejected') AS pagos
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
  const { results: tickets } = await c.env.DB.prepare(
    `SELECT t.id, t.kind, t.letra, t.fecha, t.proveedor, t.descripcion, t.total, t.verified, t.source,
            l.score, l.status, ${PUBLIC_PAGE("t.page_id")} AS page_id
     FROM expense_ticket_links l JOIN tickets t ON t.id = l.ticket_id
     WHERE l.expense_line_id = ?1 AND l.status != 'rejected'
     ORDER BY t.total DESC`,
  )
    .bind(c.req.param("id"))
    .all();
  const { results: payRows } = await c.env.DB.prepare(
    `SELECT b.id, b.fecha, b.banco, b.descripcion, b.importe, b.kind, b.items_json,
            l.score, l.status, ${PUBLIC_PAGE("b.page_id")} AS page_id, b.page_ids_json
     FROM expense_payment_links l JOIN bank_movements b ON b.id = l.movement_id
     WHERE l.expense_line_id = ?1 AND l.status != 'rejected'
     ORDER BY b.importe DESC`,
  )
    .bind(c.req.param("id"))
    .all();
  const payments = await Promise.all(
    (payRows as { items_json: string; page_ids_json: string }[]).map(async ({ items_json, page_ids_json, ...p }) => ({
      ...p,
      items: JSON.parse(items_json) as unknown[],
      pages: await publicPages(c.env, page_ids_json),
    })),
  );
  return c.json({ ...row, tickets, payments });
});

// ---- Receipts (comprobantes) -------------------------------------------------

/** SQL expression: the page id when that page is published, else NULL. */
const PUBLIC_PAGE = (col: string) => `(SELECT p.id FROM pages p WHERE p.id = ${col} AND p.restricted = 0)`;

/** Published page ids from a page_ids_json column (restricted ones are dropped). */
async function publicPages(env: Env, json: string): Promise<{ id: number; document_id: number; page_no: number }[]> {
  const ids = (JSON.parse(json) as unknown[]).filter((x): x is number => Number.isInteger(x)).slice(0, 50);
  if (!ids.length) return [];
  const ph = ids.map((_, i) => `?${i + 1}`).join(",");
  const { results } = await env.DB.prepare(
    `SELECT id, document_id, page_no FROM pages WHERE restricted = 0 AND id IN (${ph}) ORDER BY page_no`,
  )
    .bind(...ids)
    .all<{ id: number; document_id: number; page_no: number }>();
  return results;
}

const TICKET_KINDS = new Set(["factura", "recibo", "presupuesto", "ticket", "servicio", "nota_credito", "nota_debito", "otro"]);

api.get("/tickets", async (c) => {
  const q = c.req.query();
  const where: string[] = [];
  const args: unknown[] = [];
  const add = (sql: string, v: unknown) => {
    args.push(v);
    where.push(sql.replaceAll("?", `?${args.length}`));
  };
  const periods = [...new Set(c.req.queries("period") ?? [])].filter(Boolean).slice(0, MAX_FILTER_VALUES);
  if (periods.length) {
    const ph = periods.map((p) => {
      args.push(p);
      return `?${args.length}`;
    });
    where.push(`t.period_id IN (${ph.join(",")})`);
  }
  if (q.kind && TICKET_KINDS.has(q.kind)) add("t.kind = ?", q.kind);
  if (q.q) add("(t.proveedor LIKE ? ESCAPE '\\' OR t.descripcion LIKE ? ESCAPE '\\')", `%${q.q.replace(/[\\%_]/g, (m) => `\\${m}`)}%`);
  const LINKED = "EXISTS (SELECT 1 FROM expense_ticket_links l WHERE l.ticket_id = t.id AND l.status != 'rejected')";
  if (q.linked === "1") where.push(LINKED);
  if (q.linked === "0") where.push(`NOT ${LINKED}`);
  const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";
  const page = Math.min(10_000, Math.max(1, Math.floor(intParam(q.page) ?? 1)));
  const [rows, agg] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT t.id, t.kind, t.letra, t.fecha, t.proveedor, t.descripcion, t.total, t.period_id, t.subcategoria,
              t.verified, t.source, ${PUBLIC_PAGE("t.page_id")} AS page_id, ${LINKED} AS linked
       FROM tickets t ${whereSql}
       ORDER BY t.period_id DESC, t.fecha DESC, t.id
       LIMIT ${PAGE_SIZE} OFFSET ${(page - 1) * PAGE_SIZE}`,
    ).bind(...args),
    c.env.DB.prepare(`SELECT COUNT(*) AS count, COALESCE(SUM(t.total),0) AS total FROM tickets t ${whereSql}`).bind(...args),
  ]);
  const a = (agg.results[0] ?? { count: 0, total: 0 }) as { count: number; total: number };
  return c.json({ rows: rows.results, count: a.count, total: a.total, page, pageSize: PAGE_SIZE });
});

api.get("/tickets/:id", async (c) => {
  const t = await c.env.DB.prepare(
    `SELECT t.id, t.kind, t.letra, t.fecha, t.proveedor, t.cuit, t.tipo_cmp, t.pto_vta, t.nro_cmp, t.cae, t.total,
            t.medio_pago, t.descripcion, t.period_id, t.subcategoria, t.source, t.confidence, t.verified,
            t.page_ids_json, t.document_id
     FROM tickets t WHERE t.id = ?1`,
  )
    .bind(c.req.param("id"))
    .first<{ page_ids_json: string } & Record<string, unknown>>();
  if (!t) return c.json({ error: "not_found" }, 404);
  const [items, lines] = await c.env.DB.batch([
    c.env.DB.prepare("SELECT descripcion, cantidad, importe FROM ticket_items WHERE ticket_id = ?1 ORDER BY id").bind(t.id),
    c.env.DB.prepare(
      `SELECT e.id, e.period_id, e.rubro, e.concepto, e.detalle, e.importe, l.score, l.status
       FROM expense_ticket_links l JOIN expense_lines e ON e.id = l.expense_line_id
       WHERE l.ticket_id = ?1 AND l.status != 'rejected' ORDER BY e.importe DESC`,
    ).bind(t.id),
  ]);
  const { page_ids_json, ...rest } = t;
  return c.json({ ...rest, pages: await publicPages(c.env, page_ids_json), items: items.results, lines: lines.results });
});

// ---- Dashboard and saved analyses --------------------------------------------

api.get("/stats/monthly", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT p.id, COALESCE(p.total, (SELECT SUM(importe) FROM expense_lines e WHERE e.period_id = p.id)) AS gastos,
            p.ingresos, p.egresos, p.saldo_inicial, p.saldo_final,
            (SELECT COUNT(*) FROM tickets t WHERE t.period_id = p.id) AS receipts,
            (SELECT COALESCE(SUM(e.importe),0) FROM expense_lines e WHERE e.period_id = p.id AND ${BACKED("e.id")}) AS con_comprobante,
            (SELECT COUNT(*) FROM expense_lines e WHERE e.period_id = p.id AND NOT ${BACKED("e.id")}) AS lineas_sin_comprobante
     FROM periods p ORDER BY p.id`,
  ).all();
  return c.json(results);
});

api.get("/stats/rubros", async (c) => {
  const { results } = await c.env.DB.prepare(
    "SELECT period_id AS period, rubro, SUM(importe) AS total FROM expense_lines GROUP BY period_id, rubro ORDER BY period_id, rubro",
  ).all();
  return c.json(results);
});

api.get("/stats/proveedores", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT COALESCE(t.proveedor, 'Sin identificar') AS proveedor, COUNT(*) AS comprobantes, SUM(t.total) AS total
     FROM tickets t GROUP BY 1 ORDER BY total DESC LIMIT 8`,
  ).all();
  return c.json(results);
});

// A Map, not an object literal: `ANALYSES["constructor"]` on a plain object resolves to
// Object, and Object(env) would serialise the whole environment (SESSION_SECRET included).
// Handlers only ever receive the database.
type DB = Env["DB"];
const ANALYSES = new Map<string, (db: DB) => Promise<unknown>>(Object.entries({
  // "Taxis reintegrados al encargado": receipts tagged movilidad/taxi, by month.
  "taxis-encargado": async (db: DB) => {
    const { results } = await db.prepare(
      `SELECT t.id, t.fecha, t.period_id, t.proveedor, t.descripcion, t.total, t.verified, ${PUBLIC_PAGE("t.page_id")} AS page_id
       FROM tickets t
       JOIN entity_tags et ON et.entity_type = 'ticket' AND et.entity_id = t.id
       JOIN tags g ON g.id = et.tag_id AND g.name = 'movilidad/taxi'
       ORDER BY t.fecha`,
    ).all();
    return { items: results };
  },
  // Spend per rubro and year.
  "rubro-por-anio": async (db: DB) => {
    const { results } = await db.prepare(
      `SELECT substr(period_id, 1, 4) AS anio, rubro, SUM(importe) AS total, COUNT(DISTINCT period_id) AS meses
       FROM expense_lines GROUP BY anio, rubro ORDER BY anio, total DESC`,
    ).all();
    return { rows: results };
  },
  // Lines with neither a receipt nor a bank payment, only for periods with uploaded evidence.
  "sin-comprobante": async (db: DB) => {
    const { results } = await db.prepare(
      `SELECT e.id, e.period_id, e.rubro, e.concepto, e.detalle, e.importe
       FROM expense_lines e
       WHERE e.period_id IN (${EVIDENCE_PERIODS})
         AND NOT ${BACKED("e.id")}
       ORDER BY e.period_id DESC, e.importe DESC`,
    ).all();
    const { results: periods } = await db.prepare(
      `SELECT period_id AS id FROM (${EVIDENCE_PERIODS}) ORDER BY 1`,
    ).all();
    return { items: results, periods_with_receipts: periods.map((p) => (p as { id: string }).id) };
  },
}));

api.get("/analyses/:slug", async (c) => {
  const fn = ANALYSES.get(c.req.param("slug"));
  if (!fn) return c.json({ error: "not_found" }, 404);
  return c.json(await fn(c.env.DB));
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
