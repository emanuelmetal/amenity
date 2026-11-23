import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusTag } from "../components/ui";
import { api } from "../lib/api";
import { formatDate, formatMoney, formatPeriod } from "../lib/format";

const VIEWS = [
  { slug: "taxis-encargado", title: "Taxis reintegrados al encargado", text: "Comprobantes de taxi y remís, por mes." },
  { slug: "rubro-por-anio", title: "Gasto por rubro, año a año", text: "Total de cada rubro en cada año liquidado." },
  { slug: "sin-comprobante", title: "Gastos sin respaldo completo", text: "Líneas de la liquidación a las que les falta el comprobante (factura, recibo o ticket) o el pago en el resumen bancario." },
  { slug: "movimientos-sin-gasto", title: "Movimientos bancarios sin gasto", text: "Débitos del resumen bancario que todavía no están vinculados a ninguna línea de la liquidación." },
] as const;

type Slug = (typeof VIEWS)[number]["slug"];

interface TaxiItem { id: number; fecha: string | null; period_id: string; proveedor: string | null; descripcion: string | null; total: number; verified: number }
interface RubroYear { anio: string; rubro: string; total: number; meses: number }
interface MissingLine { id: number; period_id: string; rubro: string; concepto: string; detalle: string | null; importe: number; falta_comprobante: number; falta_pago: number }
interface BankItem { descripcion: string; importe: number; cantidad: number }
interface UnlinkedMovement { id: number; period_id: string; fecha: string; banco: string | null; descripcion: string; importe: number; kind: "debito" | "gastos" | "cheque"; cheque_numero: string | null; cheque_fecha_pago: string | null; page_id: number | null; items: BankItem[] }
interface MovementMonth { id: string; total: number; vinculado: number }

const th = "px-6 py-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500";
const thR = `${th} text-right`;
const td = "px-6 py-3";
const tdR = "tabular px-6 py-3 text-right text-gray-900";

function Taxis() {
  const q = useQuery({ queryKey: ["analysis", "taxis"], queryFn: () => api<{ items: TaxiItem[] }>("/analyses/taxis-encargado") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const items = q.data!.items;
  if (!items.length) return <Empty>No hay comprobantes de taxi cargados.</Empty>;
  const byMonth = new Map<string, { count: number; total: number }>();
  for (const t of items) {
    const m = byMonth.get(t.period_id) ?? { count: 0, total: 0 };
    byMonth.set(t.period_id, { count: m.count + 1, total: m.total + t.total });
  }
  const total = items.reduce((s, t) => s + t.total, 0);
  return (
    <div className="space-y-6">
      <p className="px-6 text-sm">
        <span className="tabular font-semibold text-gray-900">{items.length}</span> viajes por{" "}
        <span className="tabular font-semibold text-gray-900">{formatMoney(total)}</span> en los períodos con comprobantes cargados.
      </p>
      <table className="w-full text-sm">
        <thead className="bg-gray-50"><tr><th className={th}>Período</th><th className={thR}>Viajes</th><th className={thR}>Total</th></tr></thead>
        <tbody className="divide-y divide-gray-200">
          {[...byMonth.entries()].sort().map(([p, v]) => (
            <tr key={p}><td className={td}>{formatPeriod(p)}</td><td className={tdR}>{v.count}</td><td className={tdR}>{formatMoney(v.total)}</td></tr>
          ))}
        </tbody>
      </table>
      <table className="w-full text-sm">
        <thead className="bg-gray-50"><tr><th className={th}>Fecha</th><th className={th}>Motivo</th><th className={th}>Estado</th><th className={thR}>Importe</th></tr></thead>
        <tbody className="divide-y divide-gray-200">
          {items.map((t) => (
            <tr key={t.id}>
              <td className={`${td} whitespace-nowrap`}>{t.fecha ? formatDate(t.fecha) : formatPeriod(t.period_id)}</td>
              <td className={td}><Link className="text-gray-900 hover:text-primary" to={`/comprobantes?id=${t.id}`}>{t.descripcion ?? t.proveedor ?? "Taxi"}</Link></td>
              <td className={td}><StatusTag status={t.verified ? "verificado" : "sin-verificar"} /></td>
              <td className={tdR}>{formatMoney(t.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RubroPorAnio() {
  const q = useQuery({ queryKey: ["analysis", "rubro-por-anio"], queryFn: () => api<{ rows: RubroYear[] }>("/analyses/rubro-por-anio") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const rows = q.data!.rows;
  const years = [...new Set(rows.map((r) => r.anio))].sort();
  const rubros = [...new Set(rows.map((r) => r.rubro))];
  const get = (rubro: string, anio: string) => rows.find((r) => r.rubro === rubro && r.anio === anio);
  const months = (anio: string) => Math.max(0, ...rows.filter((r) => r.anio === anio).map((r) => r.meses));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            <th className={th}>Rubro</th>
            {years.map((y) => <th key={y} className={thR}>{y} <span className="normal-case tracking-normal text-gray-400">({months(y)} {months(y) === 1 ? "mes" : "meses"})</span></th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {rubros.map((r) => (
            <tr key={r}>
              <td className={td}><Link className="text-gray-900 hover:text-primary" to={`/gastos?rubro=${encodeURIComponent(r)}`}>{r}</Link></td>
              {years.map((y) => <td key={y} className={tdR}>{formatMoney(get(r, y)?.total ?? 0)}</td>)}
            </tr>
          ))}
          <tr className="font-semibold">
            <td className={td}>Total</td>
            {years.map((y) => <td key={y} className={tdR}>{formatMoney(rows.filter((r) => r.anio === y).reduce((s, r) => s + r.total, 0))}</td>)}
          </tr>
        </tbody>
      </table>
      <p className="mt-3 px-6 text-xs text-gray-400">Los años con pocos meses cargados no son comparables con un año completo.</p>
    </div>
  );
}

function SinComprobante() {
  const q = useQuery({
    queryKey: ["analysis", "sin-comprobante"],
    queryFn: () => api<{ items: MissingLine[]; periods_with_receipts: string[] }>("/analyses/sin-comprobante"),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { items, periods_with_receipts: periods } = q.data!;
  if (!periods.length) return <Empty>Todavía no hay comprobantes cargados para ningún período.</Empty>;
  return (
    <div className="space-y-4">
      <p className="px-6 text-sm">
        Solo se analizan los períodos con comprobantes o resumen bancario cargados: {periods.map(formatPeriod).join(", ")}. Cada gasto
        necesita las dos cosas: el comprobante de lo que se compró y el pago en el resumen bancario (cuando hay resumen de ese mes).
        Sueldos, cargas sociales y comisiones bancarias no suelen tener comprobante en el legajo.
      </p>
      {items.length ? (
        <table className="w-full text-sm">
          <thead className="bg-gray-50"><tr><th className={th}>Período</th><th className={th}>Concepto</th><th className={th}>Falta</th><th className={thR}>Importe</th></tr></thead>
          <tbody className="divide-y divide-gray-200">
            {items.map((l) => (
              <tr key={l.id}>
                <td className={`${td} whitespace-nowrap`}>{formatPeriod(l.period_id)}</td>
                <td className={td}>
                  <Link className="font-medium text-gray-900 hover:text-primary" to={`/gastos?period=${l.period_id}&q=${encodeURIComponent(l.concepto)}`}>{l.concepto}</Link>
                  <span className="block text-xs">{l.rubro}{l.detalle ? ` · ${l.detalle}` : ""}</span>
                </td>
                <td className={td}>
                  <span className="flex flex-col items-start gap-1">
                    {l.falta_comprobante ? <StatusTag status="sin-comprobante" label="Comprobante" /> : null}
                    {l.falta_pago ? <StatusTag status="sin-comprobante" label="Pago bancario" /> : null}
                  </span>
                </td>
                <td className={tdR}>{formatMoney(l.importe)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>Todos los gastos de esos períodos tienen comprobante y pago.</Empty>
      )}
    </div>
  );
}

function MovimientosSinGasto() {
  const q = useQuery({
    queryKey: ["analysis", "movimientos-sin-gasto"],
    queryFn: () => api<{ items: UnlinkedMovement[]; periods: MovementMonth[] }>("/analyses/movimientos-sin-gasto"),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { items, periods } = q.data!;
  if (!periods.length) return <Empty>Todavía no hay resúmenes bancarios cargados.</Empty>;
  return (
    <div className="space-y-6">
      <p className="px-6 text-sm">
        Transferencias a otra cuenta del consorcio, pagos que no coinciden con ninguna línea y comisiones e impuestos del banco
        (el impuesto a los débitos y créditos, Ley 25.413, se cobra sobre cada movimiento) se listan acá hasta que se vinculan.
      </p>
      <table className="w-full text-sm">
        <thead className="bg-gray-50">
          <tr><th className={th}>Mes</th><th className={thR}>Débitos</th><th className={thR}>Vinculados a gastos</th><th className={thR}>Sin vincular</th></tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {periods.map((p) => (
            <tr key={p.id}>
              <td className={`${td} whitespace-nowrap`}>{formatPeriod(p.id)}</td>
              <td className={tdR}>{formatMoney(p.total)}</td>
              <td className={tdR}>{formatMoney(p.vinculado)}</td>
              <td className={tdR}>{formatMoney(p.total - p.vinculado)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length ? (
        <table className="w-full text-sm">
          <thead className="bg-gray-50"><tr><th className={th}>Fecha</th><th className={th}>Movimiento</th><th className={thR}>Importe</th></tr></thead>
          <tbody className="divide-y divide-gray-200">
            {items.map((m) => (
              <tr key={m.id}>
                <td className={`${td} whitespace-nowrap`}>{formatDate(m.fecha)}</td>
                <td className={td}>
                  <span className="block font-medium text-gray-900">{m.kind === "gastos" ? "Comisiones e impuestos del banco" : m.descripcion}</span>
                  {m.kind === "cheque" && (
                    <span className="block text-xs">Cheque emitido, todavía sin debitar{m.cheque_fecha_pago ? ` (pagadero el ${formatDate(m.cheque_fecha_pago)})` : ""}</span>
                  )}
                  <span className="block text-xs">
                    {m.kind === "gastos" ? `${m.descripcion} · ` : ""}{m.banco ?? ""}
                    {m.page_id ? <> · <Link className="text-primary hover:underline" to={`/paginas/${m.page_id}`}>{m.kind === "cheque" ? "Ver cheque" : "Ver resumen bancario"}</Link></> : null}
                  </span>
                  {m.items.length > 0 && (
                    <ul className="mt-2 space-y-1 rounded bg-gray-50 p-2 text-xs">
                      {m.items.map((it) => (
                        <li key={it.descripcion} className="flex justify-between gap-3">
                          <span>{it.descripcion}{it.cantidad > 1 ? ` (×${it.cantidad})` : ""}</span>
                          <span className="tabular">{formatMoney(it.importe)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className={tdR}>{formatMoney(m.importe)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <Empty>Todos los movimientos bancarios están vinculados a un gasto.</Empty>
      )}
    </div>
  );
}

export default function Analisis() {
  const [params, setParams] = useSearchParams();
  const view = (VIEWS.find((v) => v.slug === params.get("ver"))?.slug ?? VIEWS[0].slug) as Slug;
  const current = VIEWS.find((v) => v.slug === view)!;
  return (
    <>
      <PageHeader title="Análisis" subtitle="Preguntas frecuentes sobre los gastos, respondidas con los datos publicados." />
      <div className="flex flex-wrap gap-2" role="tablist">
        {VIEWS.map((v) => (
          <button
            key={v.slug}
            role="tab"
            aria-selected={v.slug === view}
            onClick={() => setParams({ ver: v.slug }, { replace: true })}
            className={`h-9 rounded-lg border px-3 text-sm ${v.slug === view ? "border-primary font-semibold text-primary" : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"}`}
          >
            {v.title}
          </button>
        ))}
      </div>
      <Card bodyClassName="px-0 py-5">
        <h2 className="px-6 text-lg font-semibold text-gray-900">{current.title}</h2>
        <p className="mb-4 px-6 text-sm">{current.text}</p>
        {view === "taxis-encargado" && <Taxis />}
        {view === "rubro-por-anio" && <RubroPorAnio />}
        {view === "sin-comprobante" && <SinComprobante />}
        {view === "movimientos-sin-gasto" && <MovimientosSinGasto />}
      </Card>
    </>
  );
}
