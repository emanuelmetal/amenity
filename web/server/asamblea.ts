/**
 * "Informe para la asamblea": every series of one ejercicio (Sep–Aug) in one read-only call.
 * Aggregates only: totals per month, rubro, tipo/estado or obra. Never per unit, never CUIT,
 * never comments or access data.
 */
import { Hono } from "hono";
import { BACKED, LACKS_PAYMENT, LACKS_RECEIPT } from "./coverage";
import type { Env, SessionData } from "./env";

type Bindings = Env & { session: SessionData };

/** First month of the ejercicio. Keep in sync with EJERCICIO_START_MONTH in pipeline/alas3/config.py. */
export const EJERCICIO_START_MONTH: number = 9;
/** The complex's shared costs (Torre 3 pays its share), vs the tower's own spending. */
export const CENTRAL_RUBRO = "Gastos comunes centrales";
const HONORARIOS = "%HONORARIOS ADMINISTRACI%"; // the administrator's monthly fee line

const pad = (n: number) => String(n).padStart(2, "0");
export function ejercicioRange(year: number): { desde: string; hasta: string } {
  const end = EJERCICIO_START_MONTH === 1 ? year : year + 1;
  const last = EJERCICIO_START_MONTH === 1 ? 12 : EJERCICIO_START_MONTH - 1;
  return { desde: `${year}-${pad(EJERCICIO_START_MONTH)}`, hasta: `${end}-${pad(last)}` };
}
export function ejercicioOf(period: string): number {
  const [y, m] = period.split("-").map(Number);
  return m >= EJERCICIO_START_MONTH ? y : y - 1;
}

export const asamblea = new Hono<{ Bindings: Bindings }>();

asamblea.get("/", async (c) => {
  const db = c.env.DB;
  const { results: all } = await db.prepare("SELECT id FROM periods ORDER BY id").all<{ id: string }>();
  const ejercicios = [...new Set(all.map((p) => ejercicioOf(p.id)))].sort((a, b) => b - a);
  const raw = c.req.query("ejercicio");
  if (raw !== undefined && !/^\d{4}$/.test(raw)) return c.json({ error: "bad_request" }, 400);
  // Default: the latest complete ejercicio (it has its last month), else the latest one.
  const complete = ejercicios.filter((y) => all.some((p) => p.id === ejercicioRange(y).hasta));
  const year = raw !== undefined ? Number(raw) : (complete[0] ?? ejercicios[0]);
  if (year === undefined) return c.json({ ejercicio: null, ejercicios: [] });
  const { desde, hasta } = ejercicioRange(year);

  const lines = (cond: string) =>
    `(SELECT COALESCE(SUM(e.importe), 0) FROM expense_lines e WHERE e.period_id = p.id AND e.fondo = 0 AND ${cond})`;
  const backed = BACKED("e");
  const lackR = LACKS_RECEIPT("e");
  const lackP = LACKS_PAYMENT("e");
  const [mensual, rubros, observaciones, obras] = await Promise.all([
    db
      .prepare(
        `SELECT p.id AS mes,
                COALESCE(p.total, ${lines("1")}) AS gasto,
                ${lines("1")} AS gasto_lineas,
                p.ingresos, p.egresos, p.saldo_inicial, p.saldo_final,
                (SELECT q.saldo_final FROM periods q WHERE q.id < p.id ORDER BY q.id DESC LIMIT 1) AS saldo_anterior,
                (SELECT q.id FROM periods q WHERE q.id < p.id ORDER BY q.id DESC LIMIT 1) AS mes_anterior,
                ${lines(`e.concepto LIKE '${HONORARIOS}'`)} AS honorarios,
                ${lines(`e.rubro = '${CENTRAL_RUBRO}'`)} AS central,
                ${lines(backed)} AS respaldado,
                ${lines(`NOT ${backed} AND ${lackR} AND NOT ${lackP}`)} AS falta_comprobante,
                ${lines(`NOT ${backed} AND ${lackP} AND NOT ${lackR}`)} AS falta_pago,
                ${lines(`NOT ${backed} AND ${lackR} AND ${lackP}`)} AS falta_ambos,
                ${lines(`NOT ${backed} AND NOT ${lackR} AND NOT ${lackP}`)} AS sin_legajo
         FROM periods p WHERE p.id BETWEEN ?1 AND ?2 ORDER BY p.id`,
      )
      .bind(desde, hasta)
      .all(),
    db
      .prepare(
        `SELECT period_id AS mes, rubro, SUM(importe) AS total FROM expense_lines
         WHERE fondo = 0 AND period_id BETWEEN ?1 AND ?2 GROUP BY period_id, rubro ORDER BY period_id, rubro`,
      )
      .bind(desde, hasta)
      .all(),
    // Raised about a month of this ejercicio. Every state is shown, "descartada" included.
    db
      .prepare(
        `SELECT tipo, estado, COUNT(*) AS n, COALESCE(SUM(importe), 0) AS importe FROM observations
         WHERE period_id BETWEEN ?1 AND ?2 GROUP BY tipo, estado ORDER BY tipo, estado`,
      )
      .bind(desde, hasta)
      .all(),
    // Obras span ejercicios: all of them, with what was spent in total and in this ejercicio.
    db
      .prepare(
        `SELECT o.id, o.nombre, o.aprobado, o.criterio, o.detalle, o.acta_ids_json, o.observation_ids_json,
                COALESCE(SUM(e.importe), 0) AS gastado,
                COALESCE(SUM(CASE WHEN ${backed} THEN e.importe END), 0) AS respaldado,
                COALESCE(SUM(CASE WHEN e.period_id BETWEEN ?1 AND ?2 THEN e.importe END), 0) AS gastado_ejercicio,
                COUNT(e.id) AS lineas
         FROM obras o LEFT JOIN obra_expense_links l ON l.obra_id = o.id LEFT JOIN expense_lines e ON e.id = l.expense_line_id
         GROUP BY o.id ORDER BY o.nombre`,
      )
      .bind(desde, hasta)
      .all<Record<string, unknown> & { acta_ids_json: string; observation_ids_json: string }>(),
  ]);

  return c.json({
    ejercicio: year,
    ejercicios,
    desde,
    hasta,
    completo: all.some((p) => p.id === hasta),
    mensual: mensual.results,
    rubros: rubros.results,
    central_rubro: CENTRAL_RUBRO,
    observaciones: observaciones.results,
    obras: obras.results.map(({ acta_ids_json, observation_ids_json, ...o }) => ({
      ...o,
      actas: JSON.parse(acta_ids_json) as number[],
      observaciones: JSON.parse(observation_ids_json) as string[],
    })),
  });
});
