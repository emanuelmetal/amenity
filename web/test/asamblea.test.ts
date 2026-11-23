import { beforeEach, describe, expect, it } from "vitest";
import { sha256Hex } from "../server/auth";
import { ejercicioOf, ejercicioRange } from "../server/asamblea";
import worker from "../server/worker";
import type { AsambleaMes } from "../src/lib/api";
import { continuityGaps, coverage, feeAtInflation, feeSteps, indexSeries, pct, totalCoverage, variation } from "../src/lib/asamblea";
import { IPC } from "../src/lib/ipc";
import { fakeD1, fakeR2 } from "./fakes";

const SECRET = "x".repeat(64);
const TOKEN = "A".repeat(43);
const BASE = "https://torre3.example";

let env: any;
let raw: ReturnType<typeof fakeD1>["raw"];

async function call(path: string, cookie?: string) {
  const headers = new Headers({ "CF-Connecting-IP": "1.2.3.4" });
  if (cookie) headers.set("Cookie", cookie);
  return worker.fetch(new Request(BASE + path, { headers }), env, {} as any);
}
async function login(): Promise<string> {
  return (await call(`/acceso?k=${TOKEN}`)).headers.get("Set-Cookie")!.split(";")[0];
}
async function get(path: string): Promise<any> {
  const res = await call(path, await login());
  expect(res.status).toBe(200);
  return res.json();
}

beforeEach(async () => {
  const db = fakeD1();
  raw = db.raw;
  raw.prepare("INSERT INTO access_codes (id, code_hash, kind, unit_label) VALUES (1, ?, 'shared', 'UF-SECRETA')").run(await sha256Hex(TOKEN));
  raw.exec(`
    INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages)
      VALUES (2, 'liquidacion', '2025-09', 'Liq', 'docs/l.pdf', 'h2', 1),
             (3, 'comprobantes', '2025-09', 'Comp', 'docs/c.pdf', 'h3', 1);
    INSERT INTO pages (id, document_id, page_no, r2_key_img, text) VALUES (30, 3, 1, 'img/30.webp', 'Factura');
    -- Ejercicio 2024 (Aug 2025 only) and 2025 (Sep 2025 - Aug 2026, complete) and 2026 (Sep 2026).
    INSERT INTO periods (id, total, document_id, ingresos, egresos, saldo_inicial, saldo_final) VALUES
      ('2025-08', 900, 2, 1000, 900, 0, 100),
      ('2025-09', 1000, 2, 1200, 1000, 100, 300),
      ('2025-10', 1000, 2, 1200, 1000, 300, 500),
      ('2025-11', 1000, 2, 1000, 1000, 537, 537),
      ('2025-12', 1000, 2, 1000, 1000, 537, 537),
      ('2026-08', 1000, 2, 1000, 1000, 537, 537),
      ('2026-09', 1000, 2, 1000, 1000, 537, 537);
    INSERT INTO expense_lines (id, period_id, rubro, concepto, proveedor, cuit, importe, fondo) VALUES
      (1, '2025-09', 'Gastos comunes centrales', 'Administración central', 'Central SA', '30-11111111-1', 600, 0),
      (2, '2025-09', 'Gastos administrativos', 'HONORARIOS ADMINISTRACION', NULL, NULL, 400, 0),
      (3, '2025-10', 'Gastos administrativos', 'HONORARIOS ADMINISTRACION', NULL, NULL, 400, 0),
      (4, '2025-11', 'Gastos administrativos', 'HONORARIOS ADMINISTRACION', NULL, NULL, 500, 0),
      (5, '2025-11', 'Reparaciones', 'Pintura', NULL, NULL, 500, 0),
      (6, '2025-12', 'Fondo de obra', 'Impermeabilización', NULL, NULL, 2000, 1),
      (7, '2026-09', 'Gastos administrativos', 'HONORARIOS ADMINISTRACION', NULL, NULL, 999, 0);
    INSERT INTO tickets (id, document_id, page_id, page_ids_json, kind, fecha, proveedor, cuit, total, period_id, source, verified)
      VALUES (100, 3, 30, '[30]', 'factura', '2025-09-05', 'Central SA', '20-12345678-3', 600, '2025-09', 'qr', 1);
    INSERT INTO expense_ticket_links (expense_line_id, ticket_id, score, status) VALUES (1, 100, 1.0, 'verified');
    INSERT INTO observations (id, period_id, tipo, titulo, detalle, importe, estado, fecha) VALUES
      ('2025-11-01', '2025-11', 'otro', 'Saldo inicial distinto', 'x', 37, 'abierta', '2026-11-20'),
      ('2025-10-01', '2025-10', 'sin comprobante', 'Falta factura', 'x', 400, 'descartada', '2026-11-20'),
      ('2025-08-01', '2025-08', 'otro', 'Fuera del ejercicio', 'x', 5, 'abierta', '2026-11-20');
    INSERT INTO obras (id, nombre, aprobado, criterio, acta_ids_json, observation_ids_json)
      VALUES (9, 'Impermeabilización', 3200, '$ 50 por unidad × 64 unidades × 1 cuota', '[]', '[]');
    INSERT INTO obra_expense_links VALUES (9, 6);
    INSERT INTO comments (id, entity_type, body, author_key, access_code_id) VALUES (1, 'general', 'COMENTARIO-SECRETO', 'AUTHORKEY', 1);
  `);
  env = { DB: db.d1, FILES: fakeR2({}), SESSION_SECRET: SECRET, ASSETS: { fetch: async () => new Response("spa") } };
});

describe("ejercicio helpers", () => {
  it("runs September to August", () => {
    expect(ejercicioRange(2025)).toEqual({ desde: "2025-09", hasta: "2026-08" });
    expect(ejercicioOf("2025-09")).toBe(2025);
    expect(ejercicioOf("2026-08")).toBe(2025);
    expect(ejercicioOf("2025-08")).toBe(2024);
  });
});

describe("GET /api/asamblea", () => {
  it("needs a session", async () => {
    expect((await call("/api/asamblea")).status).not.toBe(200);
  });

  it("defaults to the latest complete ejercicio and lists them all", async () => {
    const d = await get("/api/asamblea");
    expect(d.ejercicio).toBe(2025);
    expect(d.ejercicios).toEqual([2026, 2025, 2024]);
    expect(d.completo).toBe(true);
    expect(d.mensual.map((m: any) => m.mes)).toEqual(["2025-09", "2025-10", "2025-11", "2025-12", "2026-08"]);
  });

  it("refuses a malformed ejercicio", async () => {
    const res = await call("/api/asamblea?ejercicio=2025;DROP", await login());
    expect(res.status).toBe(400);
  });

  it("returns fees, the central share, coverage and the previous closing balance", async () => {
    const d = await get("/api/asamblea?ejercicio=2025");
    const sep = d.mensual[0];
    expect(sep.honorarios).toBe(400);
    expect(sep.central).toBe(600);
    expect(sep.gasto_lineas).toBe(1000);
    // Coverage buckets add up to the lines' amount, and the receipt-linked line is backed.
    for (const m of d.mensual) {
      expect(m.respaldado + m.falta_comprobante + m.falta_pago + m.falta_ambos + m.sin_legajo).toBeCloseTo(m.gasto_lineas);
    }
    expect(sep.respaldado).toBe(600);
    expect(sep.saldo_anterior).toBe(100); // closing of 2025-08, outside the ejercicio
    // Fondo lines stay out of the monthly spending, like /stats.
    expect(d.mensual.find((m: any) => m.mes === "2025-12").gasto_lineas).toBe(0);
  });

  it("aggregates observations of the ejercicio only, descartadas included", async () => {
    const d = await get("/api/asamblea?ejercicio=2025");
    expect(d.observaciones).toEqual([
      { tipo: "otro", estado: "abierta", n: 1, importe: 37 },
      { tipo: "sin comprobante", estado: "descartada", n: 1, importe: 400 },
    ]);
  });

  it("returns obras with what was spent and backed", async () => {
    const d = await get("/api/asamblea?ejercicio=2025");
    expect(d.obras).toEqual([
      expect.objectContaining({ nombre: "Impermeabilización", aprobado: 3200, gastado: 2000, gastado_ejercicio: 2000, lineas: 1, actas: [], observaciones: [] }),
    ]);
  });

  it("never returns CUITs, unit labels, comments or authors", async () => {
    const body = JSON.stringify(await get("/api/asamblea?ejercicio=2025"));
    for (const secret of ["30-11111111-1", "20-12345678-3", "UF-SECRETA", "COMENTARIO-SECRETO", "AUTHORKEY", "code_hash"]) {
      expect(body).not.toContain(secret);
    }
  });

  it("returns an empty ejercicio for a year without liquidaciones", async () => {
    const d = await get("/api/asamblea?ejercicio=2019");
    expect(d.ejercicio).toBe(2019);
    expect(d.mensual).toEqual([]);
  });

  it("is empty without periods", async () => {
    raw.exec("DELETE FROM expense_lines; DELETE FROM periods;");
    expect(await get("/api/asamblea")).toEqual({ ejercicio: null, ejercicios: [] });
  });
});

const mes = (m: string, o: Partial<AsambleaMes> = {}): AsambleaMes => ({
  mes: m, gasto: 100, gasto_lineas: 100, ingresos: 100, egresos: 100, saldo_inicial: 0, saldo_final: 0,
  saldo_anterior: null, mes_anterior: null, honorarios: 0, central: 0,
  respaldado: 0, falta_comprobante: 0, falta_pago: 0, falta_ambos: 0, sin_legajo: 100, ...o,
});

describe("asamblea computations", () => {
  const ipc = { "2026-01": 100, "2026-02": 110, "2026-03": 121, "2026-04": 133.1 };

  it("finds every saldo gap, to the centavo", () => {
    const gaps = continuityGaps([
      mes("2026-01", { saldo_inicial: 10, saldo_anterior: null }),
      mes("2026-02", { saldo_inicial: 5195983.24, saldo_anterior: 5158983.24, mes_anterior: "2026-01" }),
      mes("2026-03", { saldo_inicial: 9172175.3, saldo_anterior: 9181175.3, mes_anterior: "2026-02" }),
      mes("2026-04", { saldo_inicial: 5463238.37, saldo_anterior: 5463258.37, mes_anterior: "2026-03" }),
      mes("2026-05", { saldo_inicial: 7.004, saldo_anterior: 7, mes_anterior: "2026-04" }),
      // 2026-06 missing: July is compared with nothing, not with May.
      mes("2026-07", { saldo_inicial: 1, saldo_anterior: 7, mes_anterior: "2026-05" }),
      mes("2027-01", { saldo_inicial: 2, saldo_anterior: 1, mes_anterior: "2026-12" }),
    ]);
    expect(gaps.map((g) => [g.mes, g.diferencia])).toEqual([
      ["2026-02", 37000],
      ["2026-03", -9000],
      ["2026-04", -20],
      ["2027-01", 1],
    ]);
  });

  it("lists fee changes with their %", () => {
    const steps = feeSteps([mes("2026-01", { honorarios: 520000 }), mes("2026-02", { honorarios: 704000 }), mes("2026-03", { honorarios: 704000 }), mes("2026-04", { honorarios: 770000 })]);
    expect(steps.map((s) => s.mes)).toEqual(["2026-01", "2026-02", "2026-04"]);
    expect(steps[1].pct).toBeCloseTo(35.38, 2);
    expect(steps[0].pct).toBeNull();
  });

  it("adjusts the first fee by IPC and indexes to base 100", () => {
    const meses = [mes("2026-01", { honorarios: 100 }), mes("2026-02", { honorarios: 100 }), mes("2026-03", { honorarios: 150, gasto: 400 })];
    feeAtInflation(meses, ipc).forEach((v, i) => expect(v).toBeCloseTo([100, 110, 121][i]));
    const idx = indexSeries(meses, ipc);
    expect(idx[0]).toEqual({ mes: "2026-01", gasto: 100, honorarios: 100, ipc: 100 });
    expect(idx[2].honorarios).toBe(150);
    expect(idx[2].gasto).toBe(200); // 3-month average (100,100,400) = 200 vs 100
    expect(indexSeries([mes("2026-05")], ipc)[0].ipc).toBeNull(); // IPC not published yet
  });

  it("compares the last 3 months with the first 3 against IPC", () => {
    const meses = ["2026-01", "2026-02", "2026-03", "2026-04"].map((m, i) => mes(m, { gasto: [100, 100, 121, 121][i] }));
    const v = variation(meses, ipc)!;
    expect(v.desde).toEqual(["2026-01", "2026-02"]);
    expect(v.nominal).toBeCloseTo(21);
    expect(v.ipc).toBeCloseTo(21);
    expect(v.real).toBeCloseTo(0);
    expect(variation(meses.slice(0, 3), ipc)).toBeNull();
  });

  it("computes coverage over the lines of months with documentation only", () => {
    const meses = [
      mes("2026-01", { respaldado: 50, falta_pago: 50, sin_legajo: 0 }),
      mes("2026-02", { respaldado: 100, sin_legajo: 0 }),
      mes("2026-03"), // nothing uploaded for this month: left out, never "the worst month"
    ];
    expect(totalCoverage(meses)).toBe(75);
    expect(coverage(meses).map((c) => c.pct)).toEqual([50, 100, null]);
    expect(totalCoverage([mes("2026-03")])).toBeNull();
  });

  it("formats percentages without a negative zero", () => {
    expect(pct(-0.04)).toBe("0 %");
    expect(pct(35.38)).toBe("+35,4 %");
    expect(pct(-9)).toBe("-9 %");
  });

  it("indexes fees only from the first month's fee", () => {
    const idx = indexSeries([mes("2026-01"), mes("2026-02", { honorarios: 100 })], { "2026-01": 100, "2026-02": 110 });
    expect(idx.map((i) => i.honorarios)).toEqual([null, null]);
    expect(idx[1].ipc).toBeCloseTo(105); // 3-month trailing average, like the spending
  });
});

describe("IPC table (make ipc)", () => {
  it("has consecutive months with a positive, mostly rising index", () => {
    const months = Object.keys(IPC).sort();
    expect(months.length).toBeGreaterThan(12);
    for (let i = 1; i < months.length; i++) {
      const [y, m] = months[i - 1].split("-").map(Number);
      expect(months[i]).toBe(`${y + (m === 12 ? 1 : 0)}-${String((m % 12) + 1).padStart(2, "0")}`);
      expect(IPC[months[i]]).toBeGreaterThan(0);
    }
    expect(IPC[months.at(-1)!]).toBeGreaterThan(IPC[months[0]]);
  });
});
