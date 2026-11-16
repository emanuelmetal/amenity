const money = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS" });
const moneyRound = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MONTHS_LONG = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

export const formatMoney = (n: number | null | undefined) => (n == null ? "—" : money.format(n));
/** KPI tiles: no decimals. */
export const formatMoneyRound = (n: number | null | undefined) => (n == null ? "—" : moneyRound.format(n));

/** `2026-11-14` → `14 nov 2026` */
export function formatDate(d: Date | string): string {
  const date = typeof d === "string" ? new Date(d.length === 10 ? `${d}T12:00:00` : d) : d;
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

/** `2026-10` → `octubre 2026` */
export function formatPeriod(p: string | null | undefined): string {
  if (!p) return "—";
  const [y, m] = p.split("-").map(Number);
  return m ? `${MONTHS_LONG[m - 1]} ${y}` : p;
}

/** Chart axes: `$4,5 M`, `$850 mil`. */
export function formatMoneyShort(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e6) return `$${(n / 1e6).toLocaleString("es-AR", { maximumFractionDigits: 1 })} M`;
  if (a >= 1e3) return `$${Math.round(n / 1e3).toLocaleString("es-AR")} mil`;
  return `$${Math.round(n).toLocaleString("es-AR")}`;
}

/** `2026-10` → `oct 26` (chart axes). */
export function formatPeriodShort(p: string): string {
  const [y, m] = p.split("-").map(Number);
  return m ? `${MONTHS[m - 1]} ${String(y).slice(2)}` : p;
}

export const TICKET_KIND_LABEL: Record<string, string> = {
  factura: "Factura", recibo: "Recibo", presupuesto: "Presupuesto", ticket: "Ticket", servicio: "Servicio",
  nota_credito: "Nota de crédito", nota_debito: "Nota de débito", otro: "Otro",
};
