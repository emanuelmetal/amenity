import { beforeEach, describe, expect, it } from "vitest";
import { sign } from "hono/jwt";
import worker from "../server/worker";
import { RATE_LIMIT_PER_HOUR, sha256Hex } from "../server/auth";
import { toFtsQuery } from "../server/api";
import { fakeD1, fakeR2 } from "./fakes";

const SECRET = "x".repeat(64);
const TOKEN = "A".repeat(43);
const ADMIN_TOKEN = "B".repeat(43);
const BASE = "https://torre3.example";

let env: any;
let raw: ReturnType<typeof fakeD1>["raw"];

async function call(path: string, init: RequestInit & { cookie?: string; ip?: string } = {}) {
  const headers = new Headers(init.headers);
  if (init.cookie) headers.set("Cookie", init.cookie);
  headers.set("CF-Connecting-IP", init.ip ?? "1.2.3.4");
  return worker.fetch(new Request(BASE + path, { ...init, headers }), env, {} as any);
}

async function login(token = TOKEN): Promise<string> {
  const res = await call(`/acceso?k=${token}`);
  expect(res.status).toBe(302);
  return res.headers.get("Set-Cookie")!.split(";")[0];
}

beforeEach(async () => {
  const db = fakeD1();
  raw = db.raw;
  raw.prepare("INSERT INTO access_codes (id, code_hash, kind) VALUES (1, ?, 'shared')").run(await sha256Hex(TOKEN));
  raw.prepare("INSERT INTO access_codes (id, code_hash, kind) VALUES (2, ?, 'admin')").run(await sha256Hex(ADMIN_TOKEN));
  raw.exec(`
    INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages)
      VALUES (1, 'reglamento', NULL, 'Reglamento', 'docs/r.pdf', 'h1', 2),
             (2, 'liquidacion', '2026-10', 'Liquidación oct 2026', 'docs/l.pdf', 'h2', 2);
    INSERT INTO pages (id, document_id, page_no, r2_key_img, text, restricted)
      VALUES (10, 1, 1, 'img/10.webp', 'Artículo 1 Del uso de las cocheras', 0),
             (11, 1, 2, 'img/11.webp', 'Artículo 2 Mascotas', 0),
             (20, 2, 1, 'img/20.webp', 'Rubro 1 pintura', 0),
             (21, 2, 2, 'img/21.webp', 'Recibo de haberes', 1);
    INSERT INTO periods (id, total, document_id) VALUES ('2026-10', 3000, 2);
    INSERT INTO expense_lines (id, period_id, rubro, concepto, proveedor, cuit, importe, page_id, verified)
      VALUES (1, '2026-10', 'Mantenimiento', 'Pintura palier', 'Pinturas SA', '30-11111111-1', 1000, 20, 1),
             (2, '2026-10', 'Mantenimiento', 'Taxi encargado 50%_off', 'Remis', NULL, 500, 20, 0),
             (3, '2026-10', 'Sueldos', 'Sueldo encargado', NULL, NULL, 1500, 21, 1);
    INSERT INTO reglamento_articles (id, numero, orden, titulo, texto, page_ids_json)
      VALUES (1, '1', 1, 'Cocheras', 'Del uso de las cocheras', '[10]'),
             (2, '2', 2, 'Mascotas', 'Se permiten mascotas', '[11, 21]');
    INSERT INTO search_fts (entity_type, entity_id, page_id, title, body) VALUES
      ('page', 10, 10, 'Reglamento p.1', 'Artículo 1 Del uso de las cocheras'),
      ('page', 21, 21, 'Liquidación p.2', 'Recibo de haberes cocheras'),
      ('article', 1, 10, 'Artículo 1', 'Del uso de las cocheras');
    INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages)
      VALUES (3, 'comprobantes', '2026-10', 'Comprobantes oct 2026', 'docs/c.pdf', 'h3', 2);
    INSERT INTO pages (id, document_id, page_no, r2_key_img, text, restricted)
      VALUES (30, 3, 1, 'img/30.webp', 'Factura', 0), (31, 3, 2, 'img/31.webp', 'Recibo de haberes', 1);
    INSERT INTO tickets (id, document_id, page_id, page_ids_json, kind, fecha, proveedor, total, period_id, source, verified)
      VALUES (100, 3, 30, '[30]', 'factura', '2026-10-05', 'Pinturas SA', 1000, '2026-10', 'qr', 1),
             (101, 3, 31, '[31, 30]', 'ticket', '2026-10-06', 'Taxi', 500, '2026-10', 'llm', 0);
    INSERT INTO expense_ticket_links VALUES (1, 100, 1.0, 'verified'), (2, 101, 0.75, 'auto'), (3, 100, 0.2, 'rejected');
    INSERT INTO tags (id, name) VALUES (1, 'movilidad/taxi');
    INSERT INTO entity_tags VALUES ('ticket', 101, 1);
    UPDATE periods SET ingresos = 3500, egresos = 3000, saldo_inicial = 100, saldo_final = 600 WHERE id = '2026-10';
  `);
  env = {
    DB: db.d1,
    FILES: fakeR2({ "img/10.webp": "IMG10", "img/21.webp": "SECRET", "docs/r.pdf": "PDF" }),
    SESSION_SECRET: SECRET,
    ASSETS: { fetch: async () => new Response("<html>spa</html>", { headers: { "Content-Type": "text/html" } }) },
  };
});

describe("access gate", () => {
  it("denies API, files and the SPA without a cookie", async () => {
    for (const p of ["/api/expenses", "/api/files/page/10", "/api/files/doc/1", "/api/tickets", "/api/tickets/100",
                     "/api/stats/monthly", "/api/stats/rubros", "/api/stats/proveedores", "/api/analyses/taxis-encargado", "/api/observations"]) {
      const res = await call(p);
      expect(res.status, p).toBe(401);
      expect(await res.text()).not.toContain("IMG10");
    }
    const page = await call("/");
    expect(page.status).toBe(401);
    expect(await page.text()).toContain("Pedí el enlace de acceso a la comisión");
  });

  it("always sends noindex and no-referrer", async () => {
    for (const res of [await call("/"), await call("/api/me", { cookie: await login() })]) {
      expect(res.headers.get("X-Robots-Tag")).toContain("noindex");
      expect(res.headers.get("Referrer-Policy")).toBe("no-referrer");
    }
  });

  it("a valid link sets a hardened cookie and redirects without the token", async () => {
    const res = await call(`/acceso?k=${TOKEN}`);
    expect(res.status).toBe(302);
    expect(res.headers.get("Location")).toBe("/");
    const cookie = res.headers.get("Set-Cookie")!;
    expect(cookie).toMatch(/^t3s=/);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("SameSite=Lax");
    const row = raw.prepare("SELECT uses, last_used_at FROM access_codes WHERE id = 1").get() as any;
    expect(row.uses).toBe(1);
    expect(row.last_used_at).not.toBeNull();
  });

  it("the cookie opens the SPA and the API", async () => {
    const cookie = await login();
    expect((await call("/", { cookie })).status).toBe(200);
    const me = await call("/api/me", { cookie });
    expect(await me.json()).toEqual({ kind: "shared" });
  });

  it("rejects unknown, malformed and inactive tokens", async () => {
    expect((await call(`/acceso?k=${"Z".repeat(43)}`)).status).toBe(401);
    expect((await call(`/acceso?k=short`)).status).toBe(401);
    expect((await call(`/acceso`)).status).toBe(401);
    raw.exec("UPDATE access_codes SET active = 0 WHERE id = 1");
    expect((await call(`/acceso?k=${TOKEN}`)).status).toBe(401);
  });

  it("rejects expired codes", async () => {
    raw.exec("UPDATE access_codes SET expires_at = '2000-01-01 00:00:00' WHERE id = 1");
    expect((await call(`/acceso?k=${TOKEN}`)).status).toBe(401);
  });

  it("revoking a code ends existing sessions", async () => {
    const cookie = await login();
    expect((await call("/api/me", { cookie })).status).toBe(200);
    raw.exec("UPDATE access_codes SET active = 0 WHERE id = 1");
    expect((await call("/api/me", { cookie })).status).toBe(401);
  });

  it("rejects forged, tampered and expired cookies", async () => {
    const forged = await sign({ cid: 1, kind: "admin", did: "d", exp: 9999999999 }, "y".repeat(64), "HS256");
    expect((await call("/api/me", { cookie: `t3s=${forged}` })).status).toBe(401);
    const good = (await login()).slice(4);
    const [h, p, s] = good.split(".");
    const tampered = `${h}.${p}.${s.slice(0, -2)}${s.endsWith("AA") ? "BB" : "AA"}`;
    expect((await call("/api/me", { cookie: `t3s=${tampered}` })).status).toBe(401);
    const expired = await sign({ cid: 1, kind: "shared", did: "d", exp: 1000 }, SECRET, "HS256");
    expect((await call("/api/me", { cookie: `t3s=${expired}` })).status).toBe(401);
    const none = `${btoa('{"alg":"none","typ":"JWT"}')}.${btoa('{"cid":1,"did":"d"}')}.`;
    expect((await call("/api/me", { cookie: `t3s=${none}` })).status).toBe(401);
  });

  it("rate-limits /acceso per IP", async () => {
    for (let i = 0; i < RATE_LIMIT_PER_HOUR; i++) {
      expect((await call(`/acceso?k=${"Z".repeat(43)}`, { ip: "9.9.9.9" })).status).toBe(401);
    }
    expect((await call(`/acceso?k=${"Y".repeat(43)}`, { ip: "9.9.9.9" })).status).toBe(429);
    // a valid link still works from that IP: only failures are limited
    expect((await call(`/acceso?k=${TOKEN}`, { ip: "9.9.9.9" })).status).toBe(302);
  });

  it("does not count successful logins (neighbours behind one CGNAT IP)", async () => {
    for (let i = 0; i < RATE_LIMIT_PER_HOUR + 5; i++) {
      expect((await call(`/acceso?k=${TOKEN}`, { ip: "7.7.7.7" })).status).toBe(302);
    }
  });

  it("sends CSP and HSTS on pages and API, but not CSP on PDFs", async () => {
    const page = await call("/");
    expect(page.headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(page.headers.get("Strict-Transport-Security")).toContain("max-age");
    const cookie = await login();
    const pdf = await call("/api/files/doc/1", { cookie });
    expect(pdf.status).toBe(200);
    expect(pdf.headers.get("Content-Security-Policy")).toBeNull();
    expect(pdf.headers.get("X-Robots-Tag")).toContain("noindex");
  });

  it("refuses to run without a strong SESSION_SECRET", async () => {
    env.SESSION_SECRET = "short";
    expect((await call(`/acceso?k=${TOKEN}`)).status).toBe(500);
  });
});

describe("api", () => {
  let cookie: string;
  beforeEach(async () => {
    cookie = await login();
  });
  const get = async (p: string) => {
    const res = await call(p, { cookie });
    return { status: res.status, body: res.headers.get("Content-Type")?.includes("json") ? await res.json() : await res.text() };
  };

  it("filters expenses and aggregates", async () => {
    const { body } = await get("/api/expenses?rubro=Mantenimiento");
    expect(body.count).toBe(2);
    expect(body.total).toBe(1500);
    expect(body.rows.map((r: any) => r.id).sort()).toEqual([1, 2]);
    expect(body.rows[0]).not.toHaveProperty("cuit");
  });

  it("accepts several values per filter (repeated params)", async () => {
    expect((await get("/api/expenses?rubro=Mantenimiento&rubro=Sueldos")).body.count).toBe(3);
    expect((await get("/api/expenses?rubro=Mantenimiento&rubro=Nada")).body.count).toBe(2);
    expect((await get("/api/expenses?period=2026-10&period=2026-09&rubro=Sueldos")).body.total).toBe(1500);
    expect((await get("/api/expenses?period=2026-09")).body.count).toBe(0);
  });

  it("hides restricted page ids in expense lists and detail", async () => {
    const rows = (await get("/api/expenses?rubro=Sueldos")).body.rows;
    expect(rows[0].page_id).toBeNull();
    expect((await get("/api/expenses/3")).body.page_id).toBeNull();
    expect((await get("/api/expenses/1")).body.page_id).toBe(20);
  });

  it("clamps huge page numbers instead of failing", async () => {
    const { status, body } = await get("/api/expenses?page=1e20");
    expect(status).toBe(200);
    expect(body.page).toBe(10000);
    expect(body.rows).toEqual([]);
  });

  it("escapes LIKE wildcards in free text", async () => {
    expect((await get("/api/expenses?q=50%25_off")).body.count).toBe(1);
    expect((await get("/api/expenses?q=_x")).body.count).toBe(0); // "_" must not act as a wildcard ("Taxi")
  });

  it("ignores unknown sort columns", async () => {
    const { status, body } = await get("/api/expenses?sort=importe;DROP TABLE x&dir=asc");
    expect(status).toBe(200);
    expect(body.count).toBe(3);
  });

  it("does not expose CUIT nor link restricted pages from expense detail", async () => {
    const { body } = await get("/api/expenses/3");
    expect(body).not.toHaveProperty("cuit");
    expect(body.page_no).toBeNull();
  });

  it("serves only non-restricted pages and images", async () => {
    expect((await get("/api/files/page/10")).body).toBe("IMG10");
    expect((await get("/api/files/page/21")).status).toBe(404);
    expect((await get("/api/pages/21")).status).toBe(404);
    const p = await get("/api/pages/10");
    expect(p.body.next_id).toBe(11);
    expect(p.body.prev_id).toBeNull();
  });

  it("drops restricted pages from article page links", async () => {
    const { body } = await get("/api/reglamento/2");
    expect(body.pages.map((p: any) => p.id)).toEqual([11]);
  });

  it("searches with FTS, accent-insensitive, hiding restricted pages", async () => {
    const { body } = await get("/api/search?q=articulo");
    expect(body.length).toBeGreaterThan(0);
    const all = (await get("/api/search?q=cocheras")).body as any[];
    expect(all.map((r) => r.page_id)).not.toContain(21);
    expect(all.some((r) => r.snippet.includes("\u0002"))).toBe(true);
  });

  it("survives FTS syntax in queries", async () => {
    for (const q of ['"', "AND OR NOT", "coch*", "NEAR(", "title:x"]) {
      expect((await get(`/api/search?q=${encodeURIComponent(q)}`)).status).toBe(200);
    }
  });

  it("lists receipts and never exposes a restricted page", async () => {
    const { body } = await get("/api/tickets");
    expect(body.count).toBe(2);
    const taxi = body.rows.find((r: any) => r.id === 101);
    expect(taxi.page_id).toBeNull(); // its first page is a payroll slip
    expect(taxi.linked).toBe(1);
    const detail = (await get("/api/tickets/101")).body;
    expect(detail.pages.map((p: any) => p.id)).toEqual([30]);
    expect(detail.lines.map((l: any) => l.id)).toEqual([2]);
    expect((await get("/api/tickets?linked=0")).body.count).toBe(0);
    expect((await get("/api/tickets?kind=ticket")).body.count).toBe(1);
    expect((await get("/api/tickets?kind=bogus")).body.count).toBe(2);
  });

  it("shows linked receipts on an expense and filters lines without one", async () => {
    const e1 = (await get("/api/expenses/1")).body;
    expect(e1.tickets.map((t: any) => [t.id, t.status])).toEqual([[100, "verified"]]);
    expect((await get("/api/expenses/3")).body.tickets).toEqual([]); // the rejected link is not shown
    const sin = (await get("/api/expenses?sin_comprobante=1")).body;
    // Line 2 only has a "posible coincidencia" (score 0.75): not counted as having a receipt.
    expect(sin.rows.map((r: any) => r.id).sort()).toEqual([2, 3]);
  });

  it("shows bank payments on an expense and requires receipt and payment once a statement exists", async () => {
    raw.exec(`
      INSERT INTO bank_movements (id, document_id, page_id, page_ids_json, period_id, fecha, banco, descripcion, importe, kind, items_json)
        VALUES (500, 3, 30, '[30, 31]', '2026-10', '2026-10-31', 'Banco X', 'Gastos bancarios oct 2026', 1500, 'gastos',
                '[{"descripcion":"I.V.A.","importe":1500,"cantidad":3}]'),
               (501, 3, 31, '[31]', '2026-10', '2026-10-09', 'Banco X', 'TRANSF. REMIS', 500, 'debito', '[]'),
               (502, 3, 30, '[30]', '2026-10', '2026-10-07', 'Banco X', 'TRANSF. PINTURAS SA', 1000, 'debito', '[]');
      INSERT INTO expense_payment_links VALUES (3, 500, 1.0, 'verified'), (2, 501, 0.6, 'rejected');
    `);
    const e3 = (await get("/api/expenses/3")).body;
    expect(e3.payments).toHaveLength(1);
    expect(e3.payments[0]).toMatchObject({ id: 500, kind: "gastos", status: "verified", items: [{ descripcion: "I.V.A.", cantidad: 3 }] });
    expect(e3.payments[0].pages.map((p: any) => p.id)).toEqual([30]); // the restricted page is dropped
    expect((await get("/api/expenses/2")).body.payments).toEqual([]); // rejected: not shown
    // October has receipts and a bank statement: every line needs both. Line 1 has only its
    // receipt; line 3 is backed by the grouped bank charges alone (the statement is their voucher).
    let sin = (await get("/api/expenses?sin_comprobante=1")).body;
    expect(sin.rows.map((r: any) => r.id).sort()).toEqual([1, 2]);
    const rows = (await get("/api/expenses?period=2026-10")).body.rows;
    const flags = (id: number) => { const r = rows.find((x: any) => x.id === id); return [r.falta_comprobante, r.falta_pago]; };
    expect([flags(1), flags(2), flags(3)]).toEqual([[0, 1], [1, 1], [0, 0]]);
    expect(rows.find((r: any) => r.id === 3).pagos).toBe(1);

    raw.exec("INSERT INTO expense_payment_links VALUES (1, 502, 1.0, 'auto');");
    sin = (await get("/api/expenses?sin_comprobante=1")).body;
    expect(sin.rows.map((r: any) => r.id)).toEqual([2]);
    const [m] = (await get("/api/stats/monthly")).body;
    expect(m).toMatchObject({ con_comprobante: 2500, lineas_sin_comprobante: 1 });
    const analysis = (await get("/api/analyses/sin-comprobante")).body.items;
    expect(analysis.map((i: any) => [i.id, i.falta_comprobante, i.falta_pago])).toEqual([[2, 1, 1]]);
  });

  it("shows a cheque on its expense; one not cleared yet is not a bank statement", async () => {
    raw.exec(`
      INSERT INTO bank_movements (id, document_id, page_id, page_ids_json, period_id, fecha, banco, comprobante, descripcion, importe, kind,
                                  items_json, cheque_numero, cheque_fecha_pago)
        VALUES (600, 3, 30, '[30]', '2026-10', '2026-10-31', 'Banco X', '9971847', 'CHEQUE CAMARA RECIBIDA', 1000, 'debito', '[]',
                '09971847', '2026-10-30'),
               (601, 3, 30, '[30]', '2026-11', '2026-11-30', 'Banco X', '09971848', 'Cheque de pago diferido N° 09971848', 500, 'cheque', '[]',
                '09971848', '2026-11-30');
      INSERT INTO expense_payment_links VALUES (1, 600, 1.0, 'verified');
    `);
    const p = (await get("/api/expenses/1")).body.payments[0];
    expect(p).toMatchObject({ id: 600, kind: "debito", cheque_numero: "09971847", cheque_fecha_pago: "2026-10-30" });
    // October has a statement (movement 600); the pending cheque does not make November one.
    const body = (await get("/api/analyses/movimientos-sin-gasto")).body;
    expect(body.items.map((i: any) => [i.id, i.kind])).toEqual([[601, "cheque"]]);
    expect(body.periods.map((x: any) => x.id)).toEqual(["2026-10"]);
  });

  it("lists bank movements not linked to any expense", async () => {
    raw.exec(`
      INSERT INTO bank_movements (id, document_id, page_id, page_ids_json, period_id, fecha, banco, descripcion, importe, kind, items_json)
        VALUES (500, 3, 30, '[30]', '2026-10', '2026-10-31', 'Banco X', 'Gastos bancarios oct 2026', 1500, 'gastos',
                '[{"descripcion":"IMPUESTO LEY 25413","importe":1500,"cantidad":9}]'),
               (501, 3, 31, '[31]', '2026-10', '2026-10-09', 'Banco X', 'TRANSF. REMIS', 500, 'debito', '[]'),
               (502, 3, 30, '[30]', '2026-10', '2026-10-07', 'Banco X', 'TRANSF. PINTURAS SA', 1000, 'debito', '[]');
      INSERT INTO expense_payment_links VALUES (1, 502, 1.0, 'verified'), (2, 501, 0.6, 'rejected');
    `);
    const body = (await get("/api/analyses/movimientos-sin-gasto")).body;
    expect(body.items.map((i: any) => i.id)).toEqual([500, 501]); // newest first; a rejected link does not count
    expect(body.items[0]).toMatchObject({ kind: "gastos", items: [{ descripcion: "IMPUESTO LEY 25413", cantidad: 9 }] });
    expect(body.items[0]).not.toHaveProperty("items_json");
    expect(body.items[1].page_id).toBeNull(); // page 31 is restricted
    expect(body.periods).toEqual([{ id: "2026-10", total: 3000, vinculado: 1000 }]);
  });

  it("aggregates the dashboard and saved analyses", async () => {
    const [m] = (await get("/api/stats/monthly")).body;
    expect(m).toMatchObject({ id: "2026-10", gastos: 3000, ingresos: 3500, receipts: 2, con_comprobante: 1000, lineas_sin_comprobante: 2 });
    const taxis = (await get("/api/analyses/taxis-encargado")).body.items;
    expect(taxis.map((t: any) => [t.id, t.page_id])).toEqual([[101, null]]);
    const sin = (await get("/api/analyses/sin-comprobante")).body;
    expect(sin.items.map((i: any) => i.id)).toEqual([3, 2]);
    expect((await get("/api/analyses/nope")).status).toBe(404);
    // Inherited object keys must not resolve to a handler (Object(env) leaked SESSION_SECRET).
    for (const slug of ["constructor", "__proto__", "toString", "hasOwnProperty", "valueOf"]) {
      const res = await get(`/api/analyses/${slug}`);
      expect(res.status, slug).toBe(404);
      expect(JSON.stringify(res.body)).not.toContain(SECRET);
    }
  });

  it("lists observations with their published references only", async () => {
    raw.exec(`
      INSERT INTO observations (id, period_id, tipo, titulo, detalle, importe, estado, fecha, line_ids_json, ticket_ids_json, movement_ids_json)
        VALUES ('2026-10-01', '2026-10', 'posible doble cobro', 'Taxi cobrado dos veces', 'detalle', 500, 'abierta', '2026-11-21', '[2, 999]', '[101, 777]', '[]'),
               ('2026-09-01', '2026-09', 'sin comprobante', 'Falta factura', 'detalle', NULL, 'resuelta', '2026-11-21', '[]', '[]', '[]');
    `);
    const { body } = await get("/api/observations");
    expect(body.map((o: any) => o.id)).toEqual(["2026-10-01", "2026-09-01"]);
    expect(body[0].lines.map((l: any) => l.id)).toEqual([2]); // 999 does not exist: not shown
    expect(body[0].tickets.map((t: any) => t.id)).toEqual([101]);
    expect(body[0].movements).toEqual([]);
    expect((await get("/api/observations?estado=resuelta")).body.map((o: any) => o.id)).toEqual(["2026-09-01"]);
    expect((await get("/api/observations?estado=bogus")).body).toHaveLength(2);
    expect((await get("/api/observations?period=2026-10")).body.map((o: any) => o.id)).toEqual(["2026-10-01"]);
  });
});

describe("toFtsQuery", () => {
  it("quotes words and prefixes the last one", () => {
    expect(toFtsQuery('pintura "palier')).toBe('"pintura" "palier"*');
    expect(toFtsQuery("  ")).toBeNull();
  });

});

describe("actas", () => {
  beforeEach(() => {
    raw.exec(`
      INSERT INTO documents (id, kind, title, r2_key_pdf, sha256, pages) VALUES
        (5, 'acta', 'Libro de actas, folio 265', 'docs/a1.pdf', 'ha1', 1),
        (6, 'acta', 'Libro de actas, folio 266', 'docs/a2.pdf', 'ha2', 1),
        (7, 'acta', 'Libro de actas (foto sin transcribir)', 'docs/a3.pdf', 'ha3', 1);
      INSERT INTO pages (id, document_id, page_no, r2_key_img, text, restricted) VALUES
        (50001, 5, 1, 'img/a1.webp', 'folio 265', 0), (60001, 6, 1, 'img/a2.webp', 'folio 266', 0),
        (70001, 7, 1, 'img/a3.webp', '', 1);
      INSERT INTO actas (id, numero, fecha, tipo, resumen, asistentes_json, page_ids_json, verified)
        VALUES (900, 101, '2025-11-27', 'comision', 'Apertura de sobres', '["4 integrantes de la comisión"]', '[60001, 70001, 50001]', 0);
      INSERT INTO acta_items (id, acta_id, orden, tipo, texto, importe, observation_ids_json)
        VALUES (901, 900, 1, 'decision', 'Pintar el palier', 1000, '["2026-10-01"]'), (902, 900, 2, 'tarea', 'Pedir presupuesto', NULL, '[]');
      INSERT INTO acta_expense_links VALUES (901, 1);
      INSERT INTO observations (id, period_id, tipo, titulo, detalle, estado, fecha) VALUES
        ('2026-10-01', '2026-10', 'otro', 'Obs', 'd', 'abierta', '2026-11-21');
    `);
  });

  it("lists actas with items and shows the detail with folios in reading order, restricted ones dropped", async () => {
    const cookie = await login();
    const list = await (await call("/api/actas", { cookie })).json();
    expect(list[0].items.map((i: any) => i.id)).toEqual([901, 902]);
    const a = await (await call("/api/actas/900", { cookie })).json();
    expect(a.pages.map((p: any) => p.id)).toEqual([60001, 50001]);
    expect(a.asistentes).toEqual(["4 integrantes de la comisión"]);
    expect(a.items[0].gastos.map((g: any) => g.id)).toEqual([1]);
    expect(a.items[0].observaciones.map((o: any) => o.id)).toEqual(["2026-10-01"]);
    expect(a).not.toHaveProperty("page_ids_json");
    const e = await (await call("/api/expenses/1", { cookie })).json();
    expect(e.actas.map((x: any) => x.id)).toEqual([901]);
    expect((await call("/api/actas/1", { cookie })).status).toBe(404);
  });
});

describe("comments", () => {
  const json = (body: unknown, extra: Record<string, string> = {}) => ({
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", Origin: BASE, ...extra },
  });
  const post = (cookie: string, path: string, body: unknown, extra?: Record<string, string>) =>
    call(path, { ...json(body, extra), cookie });

  it("posts anonymously and never exposes the author's key or access code", async () => {
    const a = await login();
    const res = await post(a, "/api/comments", { entity_type: "expense", entity_id: 1, body: "  ¿Por qué tanto?  " });
    expect(res.status).toBe(201);
    const created = await res.json();
    expect(created).toMatchObject({ body: "¿Por qué tanto?", author: "Vecino/a anónimo/a", mine: true });
    const stored = raw.prepare("SELECT author_key, access_code_id FROM comments").get() as any;
    expect(stored.access_code_id).toBe(1);
    expect(stored.author_key).toMatch(/^[0-9a-f]{64}$/);
    const b = await login();
    for (const path of ["/api/comments?entity_type=expense&entity_id=1", "/api/comments/recent"]) {
      const text = await (await call(path, { cookie: b })).text();
      expect(text).not.toContain(stored.author_key);
      expect(text).not.toContain("access_code");
      expect(JSON.parse(text)[0]).toMatchObject({ mine: false, author: "Vecino/a anónimo/a" });
    }
    expect((await (await call("/api/comments/recent", { cookie: a })).json())[0]).toMatchObject({
      mine: true,
      label: "Pintura palier · 2026-10",
    });
  });

  it("refuses writes from other origins or without JSON", async () => {
    const a = await login();
    const body = { entity_type: "general", body: "hola" };
    expect((await post(a, "/api/comments", body, { Origin: "https://evil.example" })).status).toBe(403);
    expect((await call("/api/comments", { method: "POST", body: JSON.stringify(body), cookie: a, headers: { "Content-Type": "application/json" } })).status).toBe(403);
    expect((await post(a, "/api/comments", body, { "Content-Type": "text/plain" })).status).toBe(415);
    expect(raw.prepare("SELECT count(*) AS n FROM comments").get()).toEqual({ n: 0 });
    // and nothing without a session at all
    expect((await call("/api/comments", json(body))).status).toBe(401);
  });

  it("validates the target and the body", async () => {
    const a = await login();
    const bad = async (b: unknown) => (await post(a, "/api/comments", b)).status;
    expect(await bad({ entity_type: "pages", entity_id: 10, body: "x" })).toBe(400);
    expect(await bad({ entity_type: "expense", entity_id: 12345, body: "x" })).toBe(404);
    expect(await bad({ entity_type: "expense", entity_id: "1 OR 1=1", body: "x" })).toBe(400);
    expect(await bad({ entity_type: "general", entity_id: 3, body: "x" })).toBe(400);
    expect(await bad({ entity_type: "general", body: "   " })).toBe(400);
    expect(await bad({ entity_type: "general", body: "x".repeat(2001) })).toBe(400);
    expect(await bad({ entity_type: "general", body: "mi CUIL es 20-12345678-3" })).toBe(400);
    expect(await bad({ entity_type: "general", body: "x".repeat(2000) })).toBe(201);
    expect(await bad({ entity_type: "article", entity_id: "2", body: "ok" })).toBe(201);
  });

  it("limits each device to 10 comments a day", async () => {
    const a = await login();
    for (let i = 0; i < 10; i++) expect((await post(a, "/api/comments", { entity_type: "general", body: `c${i}` })).status).toBe(201);
    expect((await post(a, "/api/comments", { entity_type: "general", body: "otro" })).status).toBe(429);
    const b = await login(); // another device is not affected
    expect((await post(b, "/api/comments", { entity_type: "general", body: "otro" })).status).toBe(201);
  });

  it("lets authors delete only their own comments", async () => {
    const a = await login();
    const b = await login();
    const { id } = await (await post(a, "/api/comments", { entity_type: "general", body: "mío" })).json();
    expect((await call(`/api/comments/${id}`, { method: "DELETE", cookie: b, headers: { Origin: BASE } })).status).toBe(404);
    expect((await call(`/api/comments/${id}`, { method: "DELETE", cookie: a })).status).toBe(403); // no Origin
    expect((await call(`/api/comments/${id}`, { method: "DELETE", cookie: a, headers: { Origin: BASE } })).status).toBe(200);
    expect(await (await call("/api/comments?entity_type=general", { cookie: a })).json()).toEqual([]);
  });

  it("hides after 3 reports from distinct devices; two moderators restore and hide, logged", async () => {
    const author = await login();
    const { id } = await (await post(author, "/api/comments", { entity_type: "general", body: "insulto" })).json();
    const list = async (cookie: string) => (await (await call("/api/comments?entity_type=general", { cookie })).json()) as any[];
    await post(author, `/api/comments/${id}/report`, {}); // self-report: ignored
    const r1 = await login();
    await post(r1, `/api/comments/${id}/report`, {});
    await post(r1, `/api/comments/${id}/report`, {}); // same device twice: one report
    const r2 = await login();
    await post(r2, `/api/comments/${id}/report`, {});
    expect(await list(r2)).toHaveLength(1);
    const r3 = await login();
    await post(r3, `/api/comments/${id}/report`, {});
    expect(await list(r3)).toEqual([]); // hidden for neighbours

    // neighbours cannot moderate
    expect((await post(r3, `/api/comments/${id}/moderate`, { action: "restore" })).status).toBe(403);
    expect((await call("/api/moderation", { cookie: r3 })).status).toBe(403);

    raw.prepare("INSERT INTO access_codes (id, code_hash, kind) VALUES (3, ?, 'admin')").run(await sha256Hex("C".repeat(43)));
    const modA = await login(ADMIN_TOKEN);
    const modB = await login("C".repeat(43));
    const seen = await list(modA);
    expect(seen[0]).toMatchObject({ status: "hidden", reports: 3 });
    expect(JSON.stringify(seen)).not.toContain("author_key");
    expect((await post(modA, `/api/comments/${id}/moderate`, { action: "restore" })).status).toBe(200);
    expect(await list(r3)).toHaveLength(1);
    const r4 = await login(); // after a moderator's decision, reports no longer auto-hide
    await post(r4, `/api/comments/${id}/report`, {});
    expect(await list(r3)).toHaveLength(1);
    expect((await post(modB, `/api/comments/${id}/moderate`, { action: "hide" })).status).toBe(200);
    expect(await list(r3)).toEqual([]);
    const queue = await (await call("/api/moderation", { cookie: modB })).json();
    expect(queue[0].history.map((h: any) => [h.action, h.moderator])).toEqual([["restore", 2], ["hide", 3]]);
    expect(JSON.stringify(queue)).not.toContain("access_code_id");
    expect((await post(modA, `/api/comments/${id}/moderate`, { action: "delete" })).status).toBe(400);
  });
});

describe("comments: review fixes", () => {
  const post = (cookie: string, path: string, body: unknown) =>
    call(path, { method: "POST", body: JSON.stringify(body), cookie, headers: { "Content-Type": "application/json", Origin: BASE } });

  it("rejects inherited entity names and non-object bodies with 400", async () => {
    const a = await login();
    expect((await post(a, "/api/comments", { entity_type: "constructor", body: "x" })).status).toBe(400);
    expect((await post(a, "/api/comments", null)).status).toBe(400);
    expect((await call("/api/comments?entity_type=toString", { cookie: a })).status).toBe(400);
  });

  it("counts reports and the daily limit per access code on unit links", async () => {
    const UNIT = "D".repeat(43);
    raw.prepare("INSERT INTO access_codes (id, code_hash, kind, unit_label) VALUES (9, ?, 'unit', 'UF1')").run(await sha256Hex(UNIT));
    const author = await login();
    const { id } = await (await post(author, "/api/comments", { entity_type: "general", body: "hola" })).json();
    for (let i = 0; i < 3; i++) await post(await login(UNIT), `/api/comments/${id}/report`, {});
    expect(raw.prepare("SELECT reports, status FROM comments WHERE id = ?").get(id)).toEqual({ reports: 1, status: "visible" });
    for (let i = 0; i < 10; i++) expect((await post(await login(UNIT), "/api/comments", { entity_type: "general", body: `u${i}` })).status).toBe(201);
    expect((await post(await login(UNIT), "/api/comments", { entity_type: "general", body: "más" })).status).toBe(429);
  });

  it("drops comments on unpublished items from the feed and deleted ones from moderation", async () => {
    const a = await login();
    const { id } = await (await post(a, "/api/comments", { entity_type: "expense", entity_id: 2, body: "sobre el taxi" })).json();
    raw.exec("DELETE FROM expense_lines WHERE id = 2");
    expect(await (await call("/api/comments/recent", { cookie: a })).json()).toEqual([]);
    raw.prepare("UPDATE comments SET reports = 1 WHERE id = ?").run(id);
    await call(`/api/comments/${id}`, { method: "DELETE", cookie: a, headers: { Origin: BASE } });
    expect(await (await call("/api/moderation", { cookie: await login(ADMIN_TOKEN) })).json()).toEqual([]);
  });
});
