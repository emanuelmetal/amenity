import { beforeEach, describe, expect, it } from "vitest";
import worker from "../server/worker";
import { sha256Hex } from "../server/auth";
import { BACKED } from "../server/api";
import { DAILY_PER_USER, MAX_ROWS, SqlRejected, VIEWS, guardSql, parseReply } from "../server/ask";
import { fakeAskD1, fakeD1, fakeR2, syncAsk } from "./fakes";

const SECRET = "x".repeat(64);
const TOKEN = "A".repeat(43);
const BASE = "https://torre3.example";

let env: any;
let raw: ReturnType<typeof fakeD1>["raw"];
let askRaw: ReturnType<typeof fakeD1>["raw"];
let replies: unknown[];
let calls: any[];

async function call(path: string, init: RequestInit & { cookie?: string } = {}) {
  const headers = new Headers(init.headers);
  if (init.cookie) headers.set("Cookie", init.cookie);
  headers.set("CF-Connecting-IP", "1.2.3.4");
  return worker.fetch(new Request(BASE + path, { ...init, headers }), env, {} as any);
}

async function login(): Promise<string> {
  const res = await call(`/acceso?k=${TOKEN}`);
  return res.headers.get("Set-Cookie")!.split(";")[0];
}

async function askQ(cookie: string, pregunta: string, headers: Record<string, string> = {}) {
  return call("/api/ask", {
    method: "POST",
    cookie,
    headers: { Origin: BASE, "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ pregunta }),
  });
}

beforeEach(async () => {
  const db = fakeD1();
  raw = db.raw;
  raw.prepare("INSERT INTO access_codes (id, code_hash, kind) VALUES (1, ?, 'shared')").run(await sha256Hex(TOKEN));
  raw.exec(`
    INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages)
      VALUES (2, 'liquidacion', '2026-10', 'Liq', 'docs/l.pdf', 'h2', 1),
             (3, 'comprobantes', '2026-10', 'Comp', 'docs/c.pdf', 'h3', 1),
             (4, 'comprobantes', '2026-11', 'Comp', 'docs/d.pdf', 'h4', 1);
    INSERT INTO pages (id, document_id, page_no, r2_key_img, text) VALUES (30, 3, 1, 'img/30.webp', 'Factura');
    INSERT INTO periods (id, total, document_id) VALUES ('2026-09', 100, 2), ('2026-10', 3000, 2), ('2026-11', 50, 2);
    INSERT INTO expense_lines (id, period_id, rubro, concepto, proveedor, cuit, importe, verified)
      VALUES (1, '2026-10', 'Mantenimiento', 'Pintura palier', 'Pinturas SA', '30-11111111-1', 1000, 1),
             (2, '2026-10', 'Mantenimiento', 'Taxi encargado', 'Remis', NULL, 500, 0),
             (3, '2026-10', 'Sueldos', 'Sueldo encargado', NULL, NULL, 1500, 1),
             (4, '2026-09', 'Varios', 'Flete', NULL, NULL, 100, 0),
             (5, '2026-11', 'Varios', 'Fotocopias', NULL, NULL, 50, 0);
    INSERT INTO tickets (id, document_id, page_id, page_ids_json, kind, fecha, proveedor, cuit, total, period_id, source, verified)
      VALUES (100, 3, 30, '[30]', 'factura', '2026-10-05', 'Pinturas SA', '20-12345678-3', 1000, '2026-10', 'qr', 1),
             (101, 3, 30, '[30]', 'ticket', '2026-10-06', 'Taxi', NULL, 500, '2026-10', 'llm', 0);
    INSERT INTO expense_ticket_links VALUES (1, 100, 1.0, 'verified'), (2, 101, 0.75, 'auto'), (3, 100, 0.2, 'rejected');
    INSERT INTO bank_movements (id, document_id, period_id, fecha, descripcion, importe, kind)
      VALUES (500, 2, '2026-10', '2026-10-07', 'TRANSF PINTURAS', 1000, 'debito'),
             (501, 2, '2026-10', '2026-10-31', 'Gastos bancarios', 30, 'gastos');
    INSERT INTO expense_payment_links VALUES (1, 500, 1.0, 'verified'), (3, 501, 0.95, 'auto');
    INSERT INTO tags (id, name) VALUES (1, 'movilidad/taxi');
    INSERT INTO entity_tags VALUES ('ticket', 101, 1);
    INSERT INTO comments (id, entity_type, body, author_key, access_code_id) VALUES (1, 'general', 'hola', 'SECRETKEY', 1);
  `);
  replies = [];
  calls = [];
  const ask = fakeAskD1(raw);
  askRaw = ask.raw;
  env = {
    DB: db.d1,
    ASK_DB: ask.d1,
    FILES: fakeR2({}),
    SESSION_SECRET: SECRET,
    ASSETS: { fetch: async () => new Response("spa") },
    AI: {
      run: async (model: string, input: any) => {
        calls.push({ model, input });
        return replies.shift() ?? { response: '{"titulo":"","sql":"","motivo":"sin respuesta"}' };
      },
    },
  };
});

const OK = [
  "SELECT mes, SUM(importe) AS total FROM ask_gastos WHERE anio = 2026 AND fondo_reserva = 0 GROUP BY mes ORDER BY mes",
  "select g.concepto, c.proveedor, c.total from ask_gastos g join ask_gasto_comprobante gc on gc.gasto_id = g.id join ask_comprobantes c on c.id = gc.comprobante_id where lower(g.concepto) like '%taxi%'",
  "SELECT rubro, COUNT(*) AS lineas, ROUND(AVG(importe), 2) AS promedio FROM ask_gastos GROUP BY rubro HAVING COUNT(*) > 1 ORDER BY 2 DESC LIMIT 10",
  "SELECT * FROM ask_gastos WHERE id IN (SELECT gasto_id FROM ask_gasto_pago WHERE estado = 'confirmado')",
  "SELECT mes, CASE WHEN respaldado = 1 THEN 'sí' ELSE 'no' END AS ok FROM ask_gastos WHERE mes BETWEEN '2026-01' AND '2026-12';",
  "SELECT t.mes, t.n FROM (SELECT mes, COUNT(*) AS n FROM ask_comprobantes GROUP BY mes) t ORDER BY t.n DESC",
  "SELECT CAST(substr(mes, 6, 2) AS INTEGER) AS m, SUM(importe) AS count FROM ask_gastos GROUP BY m ORDER BY count",
  "SELECT numero, titulo FROM ask_articulos WHERE lower(texto) LIKE '%mascota%' UNION ALL SELECT numero, resumen FROM ask_actas",
  "SELECT a.fecha, i.texto FROM ask_actas a JOIN ask_acta_items i ON i.acta_id = a.id WHERE i.tipo = 'decision'",
  "SELECT g.mes, p.estado FROM ask_gastos AS g LEFT JOIN ask_gasto_pago AS p ON p.gasto_id = g.id ORDER BY g.mes;",
  "SELECT titulo FROM ask_observaciones WHERE estado NOT IN ('descartada', 'resuelta') AND detalle LIKE '%O''Brien%'",
];

const BAD = [
  "SELECT * FROM access_codes",
  "SELECT code_hash FROM access_codes",
  "SELECT * FROM comments",
  "SELECT * FROM ask_gastos, comments",
  "SELECT * FROM ask_gastos JOIN comments ON 1 = 1",
  "SELECT * FROM ask_gastos LEFT OUTER JOIN access_codes ON 1",
  "SELECT (SELECT body FROM comments) AS x FROM ask_gastos",
  "SELECT * FROM (SELECT * FROM access_codes)",
  "SELECT * FROM ask_gastos WHERE id IN comments",
  "SELECT * FROM sqlite_master",
  "SELECT name FROM sqlite_schema",
  "SELECT * FROM pragma_table_info('access_codes')",
  "SELECT * FROM ask_gastos, json_each('[1]')",
  "SELECT * FROM main.access_codes",
  "SELECT * FROM ask_gastos_base",
  "SELECT * FROM expense_lines",
  "SELECT cuit FROM ask_gastos",
  "SELECT author_key FROM ask_gastos",
  "SELECT 1; DELETE FROM comments",
  "SELECT 1 -- comment",
  "SELECT 1 /* x */",
  'SELECT "code_hash" FROM ask_gastos',
  "SELECT `x` FROM ask_gastos",
  "SELECT [x] FROM ask_gastos",
  "SELECT ?1",
  "SELECT :a",
  "SELECT x'00'",
  "SELECT randomblob(1000000000)",
  "SELECT printf('%.*c', 1000000000, 'x')",
  "SELECT load_extension('x')",
  "SELECT sqlite_version()",
  "WITH x AS (SELECT * FROM access_codes) SELECT * FROM x",
  "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
  "DELETE FROM comments",
  "UPDATE access_codes SET active = 1",
  "INSERT INTO comments VALUES (1)",
  "DROP TABLE comments",
  "PRAGMA table_list",
  "ATTACH DATABASE 'x' AS y",
  "SELECT * FROM ask_gastos AS ask_comprobantes",
  "SELECT * FROM ask_gastos a JOIN ask_gastos b ON 1 JOIN ask_gastos c ON 1 JOIN ask_gastos d ON 1",
  "SELECT * FROM ask_gastos a, ask_gastos b",
  "SELECT * FROM ask_gastos a JOIN ask_gastos b",
  "SELECT * FROM ask_gastos a JOIN ask_gastos b ON a.id = b.id, ask_gastos c",
  // parenthesised tables and joins (review finding, verified bypasses)
  "SELECT * FROM (comments) comments",
  "SELECT * FROM (access_codes) WHERE 1 = (SELECT 1 AS access_codes)",
  "SELECT c.body, a.unit_label FROM (comments) c JOIN (access_codes) a ON a.id = c.access_code_id WHERE 1 IN (SELECT 1 AS comments UNION SELECT 1 AS access_codes UNION SELECT 1 AS body UNION SELECT 1 AS unit_label UNION SELECT 1 AS access_code_id)",
  "SELECT count(*) AS sqlite_master FROM (sqlite_master)",
  "SELECT count(*) sqlite_master FROM (sqlite_master)",
  "SELECT * FROM (pragma_table_list)",
  "SELECT * FROM (ask_gastos_base)",
  "SELECT count(*) AS n FROM (ask_gastos, ask_gastos, ask_gastos, ask_gastos)",
  "SELECT * FROM (ask_gastos JOIN ask_comprobantes ON 1)",
  "SELECT * FROM ((SELECT 1 AS x))",
  "SELECT 1 AS comments FROM ask_gastos",
  "SELECT 1 AS ask_gastos_base FROM ask_gastos",
  "SELECT x.body FROM ask_gastos AS x",
  "SELECT comments.body FROM ask_gastos",
  "SELECT replace(texto, 'a', texto) AS x FROM ask_articulos",
  "SELECT\u00a0* FROM ask_gastos",
  "SELECT\u2028* FROM ask_gastos",
  "SELECT 1;;",
  "SELECT 'abc",
  "SELECT (1",
  "SELECT 1)",
  "SELECT * FROM",
  "SELECT * FROM ask_gastos WHERE concepto MATCH 'x'",
  "SELECT * FROM ask_gastos INDEXED BY idx_expense_period_rubro",
  "SELECT * FROM ask_gastos g WHERE g.code_hash = 1",
  "SELECT 1 FROM ask_gastos WHERE 1 = (SELECT 1 FROM ask_gastos UNION SELECT 1 FROM comments)",
  "SELECT ＊ FROM ask_gastos",
];

describe("guardSql", () => {
  it.each(OK)("accepts %s", (sql) => {
    expect(() => guardSql(sql)).not.toThrow();
    // and SQLite runs it against the real views
    expect(() => askRaw.prepare(`SELECT * FROM (${guardSql(sql)}) LIMIT 5`).all()).not.toThrow();
  });

  it.each(BAD)("rejects %s", (sql) => {
    expect(() => guardSql(sql)).toThrow(SqlRejected);
  });
});

describe("ask views", () => {
  it("exist with exactly the documented columns", () => {
    for (const [name, v] of Object.entries(VIEWS)) {
      for (const db of [raw, askRaw]) {
        const cols = (db.prepare(`SELECT name FROM pragma_table_info('${name}')`).all() as { name: string }[]).map((r) => r.name);
        expect(cols, name).toEqual(Object.keys(v.cols));
      }
    }
  });

  it("never expose CUITs, keys or comments", () => {
    const all = JSON.stringify(Object.keys(VIEWS).map((v) => raw.prepare(`SELECT * FROM ${v}`).all()));
    expect(all).not.toContain("30-11111111-1");
    expect(all).not.toContain("20-12345678-3");
    expect(all).not.toContain("SECRETKEY");
    expect(all).not.toContain("r2_key");
  });

  it("the ask database holds only the ask_* tables, filled from the views", () => {
    const objects = (askRaw.prepare("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").all() as { name: string }[])
      .map((r) => r.name).filter((n) => !n.startsWith("_cf_") && !n.startsWith("sqlite_") && n !== "d1_migrations").sort();
    expect(objects).toEqual(Object.keys(VIEWS).sort());
    for (const v of Object.keys(VIEWS)) {
      expect(askRaw.prepare(`SELECT * FROM ${v} ORDER BY 1`).all(), v).toEqual(raw.prepare(`SELECT * FROM ${v} ORDER BY 1`).all());
    }
  });

  it("respaldado agrees with the API's BACKED", () => {
    const api = raw.prepare(`SELECT e.id, ${BACKED("e")} AS b FROM expense_lines e ORDER BY e.id`).all() as { id: number; b: number }[];
    const view = raw.prepare("SELECT id, respaldado AS b FROM ask_gastos ORDER BY id").all() as { id: number; b: number }[];
    expect(view).toEqual(api);
    expect(new Set(view.map((r) => r.b))).toEqual(new Set([0, 1]));
  });
});

describe("parseReply", () => {
  it("reads JSON, fenced JSON and bare SQL", () => {
    expect(parseReply({ response: '{"titulo":"T","sql":"SELECT 1"}' })).toMatchObject({ titulo: "T", sql: "SELECT 1" });
    expect(parseReply({ response: 'Claro:\n```json\n{"titulo":"T","sql":"SELECT 2"}\n```' }).sql).toBe("SELECT 2");
    expect(parseReply({ response: { titulo: "T", sql: "SELECT 3" } }).sql).toBe("SELECT 3");
    expect(parseReply({ response: "```sql\nSELECT 4\n```" }).sql).toBe("SELECT 4");
  });
});

describe("POST /api/ask", () => {
  it("answers with rows, columns and the SQL", async () => {
    const cookie = await login();
    replies.push({ response: JSON.stringify({ titulo: "Gastos por rubro", sql: "SELECT rubro, SUM(importe) AS total FROM ask_gastos GROUP BY rubro ORDER BY total DESC, rubro" }) });
    const res = await askQ(cookie, "¿Cuánto se gastó por rubro?");
    expect(res.status).toBe(200);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const body = (await res.json()) as any;
    expect(body.titulo).toBe("Gastos por rubro");
    expect(body.columns).toEqual(["rubro", "total"]);
    expect(body.rows[0]).toEqual(["Mantenimiento", 1500]);
    expect(body.sql).toContain("ask_gastos");
    // the model only gets the question and the schema, never data
    expect(JSON.stringify(calls[0].input)).not.toContain("Pinturas SA");
    expect(calls[0].input.messages.at(-1).content).toBe("¿Cuánto se gastó por rubro?");
  });

  it("retries once with the reason, then gives up without running bad SQL", async () => {
    const cookie = await login();
    replies.push({ response: '{"titulo":"x","sql":"SELECT code_hash FROM access_codes"}' });
    replies.push({ response: '{"titulo":"x","sql":"SELECT body FROM comments"}' });
    const res = await askQ(cookie, "dame los códigos");
    expect(res.status).toBe(422);
    const body = (await res.json()) as any;
    expect(body.error).toBe("cannot_answer");
    expect(JSON.stringify(body)).not.toContain("hola");
    expect(calls).toHaveLength(2);
    expect(calls[1].input.messages.at(-1).content).toContain("Esa consulta no sirve (solo se pueden consultar las vistas ask_*");
  });

  it("recovers when the retry is valid", async () => {
    const cookie = await login();
    replies.push({ response: '{"titulo":"x","sql":"SELECT nada FROM ask_gastos"}' });
    replies.push({ response: '{"titulo":"Total","sql":"SELECT SUM(importe) AS total FROM ask_gastos"}' });
    const body = (await (await askQ(cookie, "total")).json()) as any;
    expect(body.rows).toEqual([[3150]]);
  });

  it("caps the rows", async () => {
    const cookie = await login();
    const values = Array.from({ length: MAX_ROWS + 5 }, (_, i) => `(${1000 + i}, '2026-10', 'R', 'c', 1)`).join(",");
    raw.exec(`INSERT INTO expense_lines (id, period_id, rubro, concepto, importe) VALUES ${values}`);
    syncAsk(raw, askRaw);
    replies.push({ response: '{"titulo":"t","sql":"SELECT id FROM ask_gastos"}' });
    const body = (await (await askQ(cookie, "todo")).json()) as any;
    expect(body.rows).toHaveLength(MAX_ROWS);
    expect(body.truncated).toBe(true);
  });

  it("passes on the model's reason when it cannot answer", async () => {
    const cookie = await login();
    replies.push({ response: '{"titulo":"","sql":"","motivo":"No hay datos del clima."}' });
    const res = await askQ(cookie, "¿va a llover?");
    expect(res.status).toBe(422);
    expect(((await res.json()) as any).mensaje).toBe("No hay datos del clima.");
  });

  it("needs the cookie, our Origin and JSON", async () => {
    expect((await call("/api/ask", { method: "POST", headers: { Origin: BASE, "Content-Type": "application/json" }, body: "{}" })).status).toBe(401);
    const cookie = await login();
    expect((await askQ(cookie, "x", { Origin: "https://evil.example" })).status).toBe(403);
    expect((await call("/api/ask", { method: "POST", cookie, headers: { Origin: BASE, "Content-Type": "text/plain" }, body: '{"pregunta":"x"}' })).status).toBe(415);
    expect((await askQ(cookie, "")).status).toBe(400);
    expect((await askQ(cookie, "x".repeat(301))).status).toBe(400);
    expect(calls).toHaveLength(0);
  });

  it("limits questions per day and does not store them", async () => {
    const cookie = await login();
    for (let i = 0; i < DAILY_PER_USER; i++) {
      replies.push({ response: '{"titulo":"t","sql":"SELECT 1 AS uno"}' });
      expect((await askQ(cookie, `pregunta secreta ${i}`)).status).toBe(200);
    }
    const res = await askQ(cookie, "una más");
    expect(res.status).toBe(429);
    expect(((await res.json()) as any).error).toBe("rate_limited");
    const status = (await (await call("/api/ask", { cookie })).json()) as any;
    expect(status.remaining).toBe(0);
    const dump = JSON.stringify(raw.prepare("SELECT * FROM ask_usage").all());
    expect(dump).not.toContain("pregunta secreta");
    expect(dump).not.toContain(SECRET);
  });

  it("runs the model's SQL on the ask database only", async () => {
    const cookie = await login();
    askRaw.exec("INSERT INTO ask_meses (mes, anio) VALUES ('1999-01', 1999)");
    replies.push({ response: '{"titulo":"t","sql":"SELECT mes FROM ask_meses WHERE anio = 1999"}' });
    expect(((await (await askQ(cookie, "x")).json()) as any).rows).toEqual([["1999-01"]]);
    expect(raw.prepare("SELECT count(*) AS n FROM ask_meses WHERE anio = 1999").get()).toEqual({ n: 0 });
  });

  it("is off without the ask database (never falls back to the main one)", async () => {
    delete env.ASK_DB;
    const cookie = await login();
    expect((await askQ(cookie, "x")).status).toBe(503);
    expect(calls).toHaveLength(0);
  });

  it("is unavailable without the AI binding", async () => {
    delete env.AI;
    const cookie = await login();
    expect((await askQ(cookie, "x")).status).toBe(503);
    expect(((await (await call("/api/ask", { cookie })).json()) as any).available).toBe(false);
  });
});
