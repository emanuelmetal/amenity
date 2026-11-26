import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, FileCheck2, Landmark, Printer, TrendingUp, Wallet } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router";
import { BalanceChart, CentralShare, CoverageChart, FeeChart, IndexChart, ObrasBars, ObservationsChart } from "../components/asambleaCharts";
import { SpendByRubroChart } from "../components/charts";
import { Button, Card, Empty, ErrorBox, KpiTile, Loading, PageHeader } from "../components/ui";
import { api, type Asamblea as AsambleaData, type Observation } from "../lib/api";
import {
  continuityGaps,
  coverage,
  feeAtInflation,
  feeSteps,
  indexSeries,
  ipcUntil,
  pct,
  totalCoverage,
  variation,
} from "../lib/asamblea";
import { formatDate, formatMoney, formatMoneyRound, formatPeriod, formatPeriodShort } from "../lib/format";

const ejercicioLabel = (y: number) => `${y}/${String(y + 1).slice(2)}`;
const link = "font-medium text-primary hover:underline";

/** One-line reading of the chart, for the owners (neutral wording: "observación", never accusations). */
function Conclusion({ children }: { children: ReactNode }) {
  return <p className="mb-4 rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-900">{children}</p>;
}

/** Observations of this ejercicio whose title matches, linked (no ids hard-coded in the page);
 *  unresolved ones first, at most `max`. */
function Related({ obs, match, max = 3 }: { obs: Observation[]; match: RegExp; max?: number }) {
  const rank = (o: Observation) => (o.estado === "abierta" || o.estado === "enviada" ? 0 : 1);
  const found = obs.filter((o) => match.test(o.titulo)).sort((a, b) => rank(a) - rank(b) || b.period_id.localeCompare(a.period_id));
  if (!found.length) return null;
  const more = found.length - max;
  return (
    <div className="mt-4 text-xs text-gray-700">
      <span className="font-semibold">Observaciones relacionadas: </span>
      {found.slice(0, max).map((o, i) => (
        <span key={o.id}>
          {i > 0 && " · "}
          <Link className={link} to={`/observaciones?period=${o.period_id}`}>
            {o.titulo}
          </Link>{" "}
          <span className="text-gray-500">({o.estado})</span>
        </span>
      ))}
      {more > 0 && (
        <>
          {" · "}
          <Link className={link} to="/observaciones">
            y {more} más
          </Link>
        </>
      )}
    </div>
  );
}

function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <Card title={title} actions={actions} className="break-inside-avoid print:border-0 print:shadow-none">
      {children}
    </Card>
  );
}

export default function Asamblea() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("ejercicio") ?? "";
  const q = useQuery({
    queryKey: ["asamblea", requested],
    queryFn: () => api<AsambleaData>(`/asamblea${requested ? `?ejercicio=${encodeURIComponent(requested)}` : ""}`),
  });
  const d = q.data;
  const obsQ = useQuery({
    queryKey: ["observations", "asamblea", d?.desde],
    queryFn: () => api<Observation[]>("/observations"),
    enabled: Boolean(d?.desde),
  });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!d || d.ejercicio === null || !d.mensual) return <Empty>Todavía no hay liquidaciones publicadas.</Empty>;
  if (!d.mensual.length)
    return (
      <>
        <PageHeader title="Informe para la asamblea" />
        <Empty>
          No hay liquidaciones del ejercicio {ejercicioLabel(d.ejercicio)}.{" "}
          <Link className={link} to="/asamblea">
            Ver el último ejercicio
          </Link>
        </Empty>
      </>
    );

  const meses = d.mensual;
  const obs = (obsQ.data ?? []).filter((o) => o.period_id >= d.desde! && o.period_id <= d.hasta!);
  const total = meses.reduce((a, m) => a + m.gasto, 0);
  const totalLines = meses.reduce((a, m) => a + m.gasto_lineas, 0);
  const central = meses.reduce((a, m) => a + m.central, 0);
  const v = variation(meses);
  const idx = indexSeries(meses);
  const ipcLast = ipcUntil(meses.map((m) => m.mes));
  const steps = feeSteps(meses);
  const feeAdj = feeAtInflation(meses);
  const lastFee = [...meses].reverse().find((m) => m.honorarios > 0);
  const lastFeeAdj = lastFee ? feeAdj[meses.indexOf(lastFee)] : null;
  const gaps = continuityGaps(meses);
  const cov = totalCoverage(meses);
  const worst = coverage(meses)
    .filter((c) => c.pct !== null)
    .sort((a, b) => a.pct! - b.pct!)[0];
  const obsRows = d.observaciones ?? [];
  const open = obsRows.filter((o) => o.estado === "abierta" || o.estado === "enviada");
  const openN = open.reduce((a, o) => a + o.n, 0);
  const openAmount = open.reduce((a, o) => a + o.importe, 0);
  const byEstado = ["abierta", "enviada", "respondida", "resuelta"]
    .map((e) => ({ e, n: obsRows.filter((o) => o.estado === e).reduce((a, o) => a + o.n, 0) }))
    .filter((x) => x.n);
  const last = meses.at(-1)!;
  const range = `${formatPeriod(meses[0].mes)} a ${formatPeriod(last.mes)}`;

  return (
    <>
      <PageHeader
        title="Informe para la asamblea"
        subtitle={
          <>
            Ejercicio {ejercicioLabel(d.ejercicio)} ({range}){d.completo ? "" : ", en curso"}. Datos publicados al {formatDate(new Date())}.
            Son observaciones para pedir explicaciones a la administración, no conclusiones legales.
          </>
        }
        actions={
          <div className="flex items-center gap-2 print:hidden">
            <select
              aria-label="Ejercicio"
              value={String(d.ejercicio)}
              onChange={(e) => setParams({ ejercicio: e.target.value })}
              className="h-9 rounded-lg border border-gray-300 bg-white px-2 text-sm text-gray-900"
            >
              {d.ejercicios.map((y) => (
                <option key={y} value={y}>
                  Ejercicio {ejercicioLabel(y)}
                </option>
              ))}
            </select>
            <Button onClick={() => window.print()}>
              <Printer size={16} /> Imprimir
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5 print:grid-cols-5">
        <KpiTile icon={<Wallet size={18} />} label="Gasto del ejercicio" value={formatMoneyRound(total)} footer={<span>{meses.length} meses</span>} />
        <KpiTile
          icon={<TrendingUp size={18} />}
          label="Gasto mensual, en términos reales"
          value={v?.real != null ? pct(v.real) : "—"}
          footer={<span>{v ? `nominal ${pct(v.nominal)} · IPC ${pct(v.ipc)}` : "faltan meses"}</span>}
        />
        <KpiTile
          icon={<FileCheck2 size={18} />}
          label="Gasto con comprobante y pago"
          value={cov == null ? "—" : `${Math.round(cov)} %`}
          footer={<span>según la documentación cargada</span>}
        />
        <KpiTile
          icon={<ClipboardCheck size={18} />}
          label="Observaciones sin resolver"
          value={openN}
          footer={<span>{formatMoneyRound(openAmount)} en juego</span>}
        />
        <KpiTile icon={<Landmark size={18} />} label={`Saldo al cierre de ${formatPeriodShort(last.mes)}`} value={formatMoneyRound(last.saldo_final)} />
      </div>

      <Section title="Gasto e inflación">
        <Conclusion>
          {v ? (
            <>
              El gasto mensual promedio de {v.hasta.map(formatPeriodShort).join(", ")} fue {pct(v.nominal)} respecto de{" "}
              {v.desde.map(formatPeriodShort).join(", ")}.
              {v.ipc != null && v.real != null ? (
                <>
                  {" "}
                  En el mismo lapso los precios subieron {pct(v.ipc)} (IPC INDEC): en términos reales el gasto {v.real >= 0 ? "creció" : "bajó"}{" "}
                  {pct(Math.abs(v.real)).replace("+", "")}.
                </>
              ) : (
                " Todavía no está publicado el IPC de esos meses."
              )}
            </>
          ) : (
            "Hacen falta al menos 4 meses para comparar."
          )}
        </Conclusion>
        <IndexChart data={idx} />
        <p className="mt-2 text-xs text-gray-500">
          Base {formatPeriod(meses[0].mes)} = 100. IPC INDEC nivel general, total nacional
          {ipcLast ? `, publicado hasta ${formatPeriod(ipcLast)}` : ""}.
        </p>
      </Section>

      <Section title="En qué se gasta" actions={<Link className={`${link} text-sm print:hidden`} to="/gastos">Ver gastos</Link>}>
        <Conclusion>
          {Math.round((central / (totalLines || 1)) * 100)} % del gasto liquidado ({formatMoneyRound(totalLines)}) figura como{" "}
          <strong>{d.central_rubro}</strong>: según la liquidación, la parte de la Torre 3 en los gastos de todo el complejo. El resto son gastos propios de la
          torre.
        </Conclusion>
        <CentralShare central={central} total={totalLines} rubro={d.central_rubro ?? ""} />
        <div className="mt-6">
          <SpendByRubroChart stats={(d.rubros ?? []).map((r) => ({ period: r.mes, rubro: r.rubro, total: r.total }))} />
        </div>
      </Section>

      <Section title="Honorarios de administración">
        <Conclusion>
          {steps.length > 1 ? (
            <>
              Cambiaron {steps.length - 1} {steps.length === 2 ? "vez" : "veces"}:{" "}
              {steps
                .slice(1)
                .map((s) => `${formatPeriodShort(s.mes)} ${formatMoneyRound(s.monto)} (${pct(s.pct)})`)
                .join(", ")}
              .
            </>
          ) : steps.length === 1 ? (
            <>No cambiaron en el ejercicio: {formatMoneyRound(steps[0].monto)} por mes.</>
          ) : (
            "No hay una línea de honorarios de administración en este ejercicio."
          )}
          {lastFee && lastFeeAdj != null && (
            <>
              {" "}
              En {formatPeriod(lastFee.mes)} se liquidaron {formatMoneyRound(lastFee.honorarios)}. Si el honorario de {formatPeriodShort(steps[0].mes)} hubiera
              seguido el IPC, sería {formatMoneyRound(lastFeeAdj)}: el liquidado está {pct((lastFee.honorarios / lastFeeAdj - 1) * 100)} respecto de esa
              referencia.
            </>
          )}
        </Conclusion>
        <FeeChart meses={meses} />
        <Related obs={obs} match={/honorario/i} />
      </Section>

      <Section title="Respaldo documental de cada gasto" actions={<Link className={`${link} text-sm print:hidden`} to="/analisis?ver=sin-comprobante">Ver cuáles</Link>}>
        <Conclusion>
          {cov == null ? (
            "No hay gastos en el ejercicio."
          ) : (
            <>
              {Math.round(cov)} % del gasto del ejercicio está respaldado con la documentación cargada en el portal: comprobante y, en los meses con resumen
              bancario, el pago desde la cuenta del consorcio. Los meses sin documentación cargada no se cuentan.
              {worst && worst.pct! < 100 && (
                <>
                  {" "}
                  El mes con menos respaldo es {formatPeriod(worst.mes)}: {Math.round(worst.pct!)} %.
                </>
              )}
            </>
          )}
        </Conclusion>
        <CoverageChart meses={meses} />
        <Related obs={obs} match={/no figuran pagados|sin comprobante|sin factura/i} />
      </Section>

      <Section title="Saldos y continuidad">
        <Conclusion>
          {gaps.length ? (
            <>
              En {gaps.length} {gaps.length === 1 ? "mes" : "meses"} el saldo inicial no coincide con el saldo final del mes anterior:{" "}
              {gaps.map((g) => `${formatPeriodShort(g.mes)} ${g.diferencia > 0 ? "+" : ""}${formatMoney(g.diferencia)}`).join(", ")}. La administración debería
              explicar cada diferencia.
            </>
          ) : (
            "Cada mes abre con el saldo con que cerró el mes anterior (cuando ambos están publicados)."
          )}
        </Conclusion>
        <BalanceChart meses={meses} gaps={gaps} />
        <Related obs={obs} match={/saldos? inicial|saldos iniciales|cierre anterior/i} />
      </Section>

      <Section title="Obras y cuotas extraordinarias">
        {d.obras?.length ? (
          <>
            <Conclusion>
              {d.obras.length} {d.obras.length === 1 ? "obra" : "obras"}: aprobado según las actas, gastado según las liquidaciones (todos los ejercicios) y la parte
              con comprobante y pago.
            </Conclusion>
            <ObrasBars obras={d.obras} />
          </>
        ) : (
          <Empty>Todavía no hay obras cargadas con su monto aprobado.</Empty>
        )}
        <Related obs={obs} match={/\bcuotas?\b|\bobras?\b|impermeabiliz|fondo de reserva/i} />
      </Section>

      <Section title="Observaciones del ejercicio" actions={<Link className={`${link} text-sm print:hidden`} to="/observaciones">Ver todas</Link>}>
        {obsRows.length ? (
          <>
            <Conclusion>
              {byEstado.map((x) => `${x.n} ${x.e}${x.n === 1 ? "" : "s"}`).join(", ")}. Sin resolver: {formatMoneyRound(openAmount)} en juego.
            </Conclusion>
            <ObservationsChart data={obsRows} />
          </>
        ) : (
          <Empty>No hay observaciones sobre meses de este ejercicio.</Empty>
        )}
      </Section>
    </>
  );
}
