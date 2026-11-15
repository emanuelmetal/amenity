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
