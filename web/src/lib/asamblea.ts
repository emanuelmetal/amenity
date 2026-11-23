/** Pure computations of the "Informe para la asamblea" page (tested in test/asamblea.test.ts). */
import type { AsambleaMes } from "./api";
import { IPC } from "./ipc";

export interface IndexPoint {
  mes: string;
  gasto: number | null; // 3-month trailing average of the month's spending, base = 100
  honorarios: number | null;
  ipc: number | null; // null where INDEC has not published yet
}

const avg = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/** 3-month trailing average (fewer at the start). */
function trailing(xs: (number | null)[]): (number | null)[] {
  return xs.map((_, i) => {
    const w = xs.slice(Math.max(0, i - 2), i + 1);
    return w.some((x) => x == null) ? null : avg(w as number[]);
  });
}

/** Spending, fees and IPC on one scale, base = the ejercicio's first month (100). Spending and
 *  IPC are both 3-month trailing averages, so they are smoothed the same way; the fee is the
 *  month's value against the first month's fee (no line when the first month has no fee). */
export function indexSeries(meses: AsambleaMes[], ipc: Record<string, number> = IPC): IndexPoint[] {
  if (!meses.length) return [];
  const g = trailing(meses.map((m) => m.gasto));
  const p = trailing(meses.map((m) => ipc[m.mes] ?? null));
  const baseFee = meses[0].honorarios;
  return meses.map((m, i) => ({
    mes: m.mes,
    gasto: g[0] && g[i] != null ? (g[i]! / g[0]) * 100 : null,
    honorarios: baseFee && m.honorarios ? (m.honorarios / baseFee) * 100 : null,
    ipc: p[0] && p[i] != null ? (p[i]! / p[0]) * 100 : null,
  }));
}

/** Last month with a published IPC among `meses`. */
export function ipcUntil(meses: string[], ipc: Record<string, number> = IPC): string | null {
  return [...meses].reverse().find((m) => ipc[m] !== undefined) ?? null;
}

export interface FeeStep {
  mes: string;
  monto: number;
  anterior: number | null;
  pct: number | null; // change vs the previous month's fee
}

/** Months where the fee changed (and the first month), with the % change. */
export function feeSteps(meses: AsambleaMes[]): FeeStep[] {
  const out: FeeStep[] = [];
  let prev: number | null = null;
  for (const m of meses) {
    if (!m.honorarios) continue;
    if (prev === null || Math.abs(m.honorarios - prev) >= 0.01) {
      out.push({ mes: m.mes, monto: m.honorarios, anterior: prev, pct: prev ? (m.honorarios / prev - 1) * 100 : null });
    }
    prev = m.honorarios;
  }
  return out;
}

/** What the first month's fee would be if it had followed the IPC (null without IPC). */
export function feeAtInflation(meses: AsambleaMes[], ipc: Record<string, number> = IPC): (number | null)[] {
  const first = meses.find((m) => m.honorarios > 0);
  if (!first || !ipc[first.mes]) return meses.map(() => null);
  return meses.map((m) => (ipc[m.mes] && m.mes >= first.mes ? (first.honorarios * ipc[m.mes]) / ipc[first.mes] : null));
}

export interface Gap {
  mes: string;
  mes_anterior: string;
  saldo_anterior: number;
  saldo_inicial: number;
  diferencia: number; // opening - previous closing
}

export function previousMonth(mes: string): string {
  const [y, m] = mes.split("-").map(Number);
  return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
}

/** Months whose opening balance differs from the previous month's closing balance (≥ 1 centavo).
 *  Only against the calendar month before: a missing liquidación is not a continuity gap. */
export function continuityGaps(meses: AsambleaMes[]): Gap[] {
  return meses
    .filter((m) => m.saldo_inicial != null && m.saldo_anterior != null && m.mes_anterior === previousMonth(m.mes))
    .map((m) => ({
      mes: m.mes,
      mes_anterior: m.mes_anterior!,
      saldo_anterior: m.saldo_anterior!,
      saldo_inicial: m.saldo_inicial!,
      diferencia: Math.round((m.saldo_inicial! - m.saldo_anterior!) * 100) / 100,
    }))
    .filter((g) => Math.abs(g.diferencia) >= 0.01);
}

export interface Variation {
  desde: string[]; // months averaged at the start
  hasta: string[]; // and at the end
  nominal: number; // % change of the average monthly spending
  ipc: number | null; // % change of the IPC over the same months
  real: number | null; // nominal deflated by the IPC
}

/** Average monthly spending of the last 3 months vs the first 3, against the IPC of the same months. */
export function variation(meses: AsambleaMes[], ipc: Record<string, number> = IPC): Variation | null {
  if (meses.length < 4) return null;
  const n = Math.min(3, Math.floor(meses.length / 2));
  const a = meses.slice(0, n);
  const b = meses.slice(-n);
  const ga = avg(a.map((m) => m.gasto));
  const gb = avg(b.map((m) => m.gasto));
  if (!ga) return null;
  const nominal = (gb / ga - 1) * 100;
  const hasIpc = [...a, ...b].every((m) => ipc[m.mes]);
  const ipcPct = hasIpc ? (avg(b.map((m) => ipc[m.mes])) / avg(a.map((m) => ipc[m.mes])) - 1) * 100 : null;
  const real = ipcPct === null ? null : ((1 + nominal / 100) / (1 + ipcPct / 100) - 1) * 100;
  return { desde: a.map((m) => m.mes), hasta: b.map((m) => m.mes), nominal, ipc: ipcPct, real };
}

export const COVERAGE_KEYS = ["respaldado", "falta_comprobante", "falta_pago", "falta_ambos", "sin_legajo"] as const;
export const COVERAGE_LABEL: Record<(typeof COVERAGE_KEYS)[number], string> = {
  respaldado: "Respaldado",
  falta_comprobante: "Falta el comprobante",
  falta_pago: "Falta el pago bancario",
  falta_ambos: "Faltan los dos",
  sin_legajo: "Mes sin documentación cargada",
};

/** Share of the lines' amount that is backed, per month and overall. Lines of months with no
 *  documentation uploaded to the portal (`sin_legajo`) are left out: that is a gap of the
 *  portal's evidence, not something to put on the administration. */
const checkable = (m: AsambleaMes) => m.gasto_lineas - m.sin_legajo;
export function coverage(meses: AsambleaMes[]): { mes: string; pct: number | null }[] {
  return meses.map((m) => ({ mes: m.mes, pct: checkable(m) > 0.005 ? (m.respaldado / checkable(m)) * 100 : null }));
}
export function totalCoverage(meses: AsambleaMes[]): number | null {
  const t = meses.reduce((a, m) => a + checkable(m), 0);
  return t > 0.005 ? (meses.reduce((a, m) => a + m.respaldado, 0) / t) * 100 : null;
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n == null) return "—";
  const r = Math.round(n * 10 ** digits) / 10 ** digits || 0; // no "-0 %"
  return `${r > 0 ? "+" : ""}${r.toLocaleString("es-AR", { maximumFractionDigits: digits })} %`;
}
