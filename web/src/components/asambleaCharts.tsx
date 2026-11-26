/** Charts of the "Informe para la asamblea" page. Same conventions as charts.tsx: the validated
 *  SERIES order, one y-axis per chart, a legend for 2+ series, a tooltip and a "Ver tabla". */
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import type { AsambleaMes, AsambleaObra, ObservationState } from "../lib/api";
import { COVERAGE_KEYS, COVERAGE_LABEL, coverage, feeAtInflation, type Gap, type IndexPoint } from "../lib/asamblea";
import { formatMoney, formatMoneyShort, formatPeriod, formatPeriodShort } from "../lib/format";
import { AXIS, GRID, Legend, OTHER, SERIES, TableView, TooltipBox, axisProps, td, th } from "./charts";

type TP = TooltipContentProps<ValueType, NameType>;
const fmtIndex = (n: number) => n.toLocaleString("es-AR", { maximumFractionDigits: 1 });
const fmtPct = (n: number | null) => (n == null ? "—" : `${Math.round(n)} %`);

// ---- Gasto, honorarios e IPC (index, base 100) ----------------------------------------------

export function IndexChart({ data }: { data: IndexPoint[] }) {
  const series = [
    { key: "gasto", label: "Gasto mensual (promedio móvil de 3 meses)", color: SERIES[0] },
    { key: "honorarios", label: "Honorarios de administración", color: SERIES[2] },
    { key: "ipc", label: "Inflación (IPC INDEC, promedio móvil de 3 meses)", color: OTHER },
  ] as const;
  return (
    <div>
      <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
      <div className="mt-2 h-64" role="img" aria-label="Gasto, honorarios e inflación, base 100">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="4 4" />
            <XAxis dataKey="mes" tickFormatter={formatPeriodShort} {...axisProps} />
            <YAxis tickFormatter={fmtIndex} width={48} domain={["auto", "auto"]} {...axisProps} />
            <ReferenceLine y={100} stroke={AXIS} strokeDasharray="2 4" />
            <Tooltip
              cursor={{ stroke: AXIS, strokeDasharray: "3 3" }}
              content={(p: TP) =>
                p.active && p.payload?.length ? (
                  <TooltipBox
                    title={formatPeriod(String(p.label))}
                    format={fmtIndex}
                    rows={series
                      .map((s) => ({ label: s.label, value: Number(p.payload.find((x) => x.dataKey === s.key)?.value), color: s.color }))
                      .filter((r) => Number.isFinite(r.value))}
                  />
                ) : null
              }
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type={s.key === "honorarios" ? "stepAfter" : "monotone"}
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.key === "ipc" ? "6 4" : undefined}
                dot={false}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>Mes</th>
              {series.map((s) => (
                <th key={s.key} className={`${th} text-right`}>{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.map((d) => (
              <tr key={d.mes}>
                <td className="whitespace-nowrap px-3 py-1.5">{formatPeriod(d.mes)}</td>
                {series.map((s) => (
                  <td key={s.key} className={td}>{d[s.key] == null ? "—" : fmtIndex(d[s.key]!)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

// ---- Honorarios: real fee vs the first fee adjusted by IPC ($) --------------------------------

export function FeeChart({ meses }: { meses: AsambleaMes[] }) {
  const adj = feeAtInflation(meses);
  const rows = meses.map((m, i) => ({ mes: m.mes, cobrado: m.honorarios || null, ipc: adj[i] }));
  const series = [
    { key: "cobrado", label: "Honorarios liquidados", color: SERIES[2] },
    { key: "ipc", label: "El primer honorario ajustado por IPC", color: OTHER },
  ] as const;
  return (
    <div>
      <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
      <div className="mt-2 h-56" role="img" aria-label="Honorarios de administración por mes">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="4 4" />
            <XAxis dataKey="mes" tickFormatter={formatPeriodShort} {...axisProps} />
            <YAxis tickFormatter={formatMoneyShort} width={72} domain={[0, "auto"]} {...axisProps} />
            <Tooltip
              cursor={{ stroke: AXIS, strokeDasharray: "3 3" }}
              content={(p: TP) =>
                p.active && p.payload?.length ? (
                  <TooltipBox
                    title={formatPeriod(String(p.label))}
                    rows={series
                      .map((s) => ({ label: s.label, value: Number(p.payload.find((x) => x.dataKey === s.key)?.value), color: s.color }))
                      .filter((r) => Number.isFinite(r.value))}
                  />
                ) : null
              }
            />
            <Line type="stepAfter" dataKey="cobrado" stroke={SERIES[2]} strokeWidth={2} dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }} isAnimationActive={false} />
            <Line type="monotone" dataKey="ipc" stroke={OTHER} strokeWidth={2} strokeDasharray="6 4" dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <TableView>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>Mes</th>
              {series.map((s) => (
                <th key={s.key} className={`${th} text-right`}>{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rows.map((r) => (
              <tr key={r.mes}>
                <td className="whitespace-nowrap px-3 py-1.5">{formatPeriod(r.mes)}</td>
                <td className={td}>{formatMoney(r.cobrado)}</td>
                <td className={td}>{formatMoney(r.ipc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

// ---- Stacked bars (respaldo by month, observaciones by tipo) -------------------------------

interface StackKey {
  key: string;
  label: string;
  color: string;
}

function StackedBars({
  rows,
  keys,
  xKey,
  xLabel,
  formatX,
  horizontal = false,
  label,
  height = "h-72",
}: {
  rows: Record<string, number | string>[];
  keys: StackKey[];
  xKey: string;
  xLabel: string;
  formatX: (v: string) => string;
  horizontal?: boolean;
  label: string;
  height?: string;
}) {
  const shown = keys.filter((k) => rows.some((r) => Number(r[k.key]) > 0));
  const tooltip = (p: TP) =>
    p.active && p.payload?.length ? (
      <TooltipBox
        title={formatX(String(p.label))}
        rows={[...p.payload]
          .reverse()
          .filter((x) => Number(x.value) > 0)
          .map((x) => {
            const k = shown.find((s) => s.key === x.dataKey)!;
            return { label: k.label, value: Number(x.value), color: k.color };
          })}
      />
    ) : null;
  return (
    <div>
      <Legend items={shown.map((k) => ({ label: k.label, color: k.color }))} />
      <div className={`mt-2 ${height}`} role="img" aria-label={label}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 8, right: 16, bottom: 0, left: 8 }} barCategoryGap="25%">
            <CartesianGrid vertical={horizontal} horizontal={!horizontal} stroke={GRID} strokeDasharray="4 4" />
            {horizontal ? (
              <>
                <XAxis type="number" tickFormatter={formatMoneyShort} {...axisProps} />
                <YAxis type="category" dataKey={xKey} width={150} tickFormatter={formatX} {...axisProps} />
              </>
            ) : (
              <>
                <XAxis dataKey={xKey} tickFormatter={formatX} {...axisProps} />
                <YAxis tickFormatter={formatMoneyShort} width={72} {...axisProps} />
              </>
            )}
            <Tooltip cursor={{ fill: "#f5f5f5" }} content={tooltip} />
            {shown.map((k, i) => (
              <Bar
                key={k.key}
                dataKey={k.key}
                stackId="s"
                fill={k.color}
                stroke="#fff"
                strokeWidth={2}
                radius={i === shown.length - 1 ? (horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>{xLabel}</th>
              {shown.map((k) => (
                <th key={k.key} className={`${th} text-right`}>{k.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rows.map((r) => (
              <tr key={String(r[xKey])}>
                <td className="whitespace-nowrap px-3 py-1.5">{formatX(String(r[xKey]))}</td>
                {shown.map((k) => (
                  <td key={k.key} className={td}>{formatMoney(Number(r[k.key]))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

export function CoverageChart({ meses }: { meses: AsambleaMes[] }) {
  const keys = COVERAGE_KEYS.map((k, i) => ({ key: k, label: COVERAGE_LABEL[k], color: k === "sin_legajo" ? OTHER : SERIES[i] }));
  const pcts = new Map(coverage(meses).map((c) => [c.mes, c.pct]));
  return (
    <div>
      <StackedBars
        rows={meses.map((m) => ({ ...m }) as unknown as Record<string, number | string>)}
        keys={keys}
        xKey="mes"
        xLabel="Mes"
        formatX={formatPeriodShort}
        label="Gasto por mes según su respaldo documental"
      />
      {/* The % is a second measure: a row of values under the bars instead of a second axis. */}
      <div className="mt-3 overflow-x-auto">
        <div className="grid min-w-max grid-flow-col gap-1 text-center text-xs" style={{ gridAutoColumns: "minmax(3rem, 1fr)" }}>
          {meses.map((m) => (
            <div key={m.mes} className="rounded-md bg-gray-50 px-1 py-1">
              <div className="text-gray-500">{formatPeriodShort(m.mes)}</div>
              <div className="tabular font-semibold text-gray-900">{fmtPct(pcts.get(m.mes) ?? null)}</div>
            </div>
          ))}
        </div>
        <p className="mt-1 text-xs text-gray-500">% del gasto del mes respaldado con la documentación cargada (sin contar los meses sin documentación).</p>
      </div>
    </div>
  );
}

const ESTADOS: { key: ObservationState; label: string }[] = [
  { key: "abierta", label: "Abierta" },
  { key: "enviada", label: "Enviada" },
  { key: "respondida", label: "Respondida" },
  { key: "resuelta", label: "Resuelta" },
];

export function ObservationsChart({ data }: { data: { tipo: string; estado: ObservationState; importe: number }[] }) {
  const tipos = [...new Set(data.map((d) => d.tipo))];
  const rows = tipos
    .map((tipo) => {
      const r: Record<string, number | string> = { tipo };
      for (const e of ESTADOS) r[e.key] = data.filter((d) => d.tipo === tipo && d.estado === e.key).reduce((a, d) => a + d.importe, 0);
      return r;
    })
    .sort((a, b) => ESTADOS.reduce((s, e) => s + Number(b[e.key]), 0) - ESTADOS.reduce((s, e) => s + Number(a[e.key]), 0));
  const keys = ESTADOS.map((e, i) => ({ key: e.key, label: e.label, color: SERIES[i] }));
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  return (
    <StackedBars
      rows={rows}
      keys={keys}
      xKey="tipo"
      xLabel="Tipo"
      formatX={cap}
      horizontal
      height={tipos.length > 5 ? "h-80" : "h-64"}
      label="Importe en juego de las observaciones por tipo y estado"
    />
  );
}

// ---- Saldos: closing balance and the month's result, with continuity gaps ---------------------

export function BalanceChart({ meses, gaps }: { meses: AsambleaMes[]; gaps: Gap[] }) {
  const rows = meses.map((m) => ({
    mes: m.mes,
    saldo: m.saldo_final,
    resultado: m.ingresos != null && m.egresos != null ? m.ingresos - m.egresos : null,
  }));
  const series = [
    { key: "saldo", label: "Saldo al cierre", color: SERIES[0] },
    { key: "resultado", label: "Ingresos − egresos del mes", color: SERIES[1] },
  ] as const;
  const gapAt = new Map(gaps.map((g) => [g.mes, g]));
  return (
    <div>
      <Legend items={[...series.map((s) => ({ label: s.label, color: s.color })), ...(gaps.length ? [{ label: "Saldo inicial distinto del cierre anterior", color: "#eb4137" }] : [])]} />
      <div className="mt-2 h-64" role="img" aria-label="Saldo al cierre y resultado de cada mes">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 12, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="4 4" />
            <XAxis dataKey="mes" tickFormatter={formatPeriodShort} {...axisProps} />
            <YAxis tickFormatter={formatMoneyShort} width={72} {...axisProps} />
            <ReferenceLine y={0} stroke={AXIS} />
            <Tooltip
              cursor={{ fill: "#f5f5f5" }}
              content={(p: TP) => {
                if (!p.active || !p.payload?.length) return null;
                const g = gapAt.get(String(p.label));
                return (
                  <div>
                    <TooltipBox
                      title={formatPeriod(String(p.label))}
                      rows={series
                        .map((s) => ({ label: s.label, value: Number(p.payload.find((x) => x.dataKey === s.key)?.value), color: s.color }))
                        .filter((r) => Number.isFinite(r.value))}
                    />
                    {g && (
                      <div className="mt-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs text-gray-900 shadow-lg">
                        Abrió con {formatMoney(g.saldo_inicial)}; {formatPeriod(g.mes_anterior)} cerró con {formatMoney(g.saldo_anterior)} ({g.diferencia > 0 ? "+" : ""}
                        {formatMoney(g.diferencia)}).
                      </div>
                    )}
                  </div>
                );
              }}
            />
            <Bar dataKey="resultado" fill={SERIES[1]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Line type="monotone" dataKey="saldo" stroke={SERIES[0]} strokeWidth={2} dot={false} activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }} isAnimationActive={false} />
            {gaps.map((g) => {
              const r = rows.find((x) => x.mes === g.mes);
              return r?.saldo != null ? (
                <ReferenceDot key={g.mes} x={g.mes} y={meses.find((m) => m.mes === g.mes)!.saldo_inicial!} r={6} fill="#eb4137" stroke="#fff" strokeWidth={2} />
              ) : null;
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <TableView>
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={th}>Mes</th>
              <th className={`${th} text-right`}>Cierre del mes anterior</th>
              <th className={`${th} text-right`}>Saldo inicial</th>
              <th className={`${th} text-right`}>Ingresos − egresos</th>
              <th className={`${th} text-right`}>Saldo al cierre</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {meses.map((m, i) => (
              <tr key={m.mes} className={gapAt.has(m.mes) ? "bg-error/5" : ""}>
                <td className="whitespace-nowrap px-3 py-1.5">
                  {formatPeriod(m.mes)}
                  {gapAt.has(m.mes) && <span className="ml-1 text-xs font-semibold text-error">no coincide</span>}
                </td>
                <td className={td}>{formatMoney(m.saldo_anterior)}</td>
                <td className={td}>{formatMoney(m.saldo_inicial)}</td>
                <td className={td}>{formatMoney(rows[i].resultado)}</td>
                <td className={td}>{formatMoney(m.saldo_final)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

// ---- Central vs own spending (one two-part bar) --------------------------------------------

export function CentralShare({ central, total, rubro }: { central: number; total: number; rubro: string }) {
  if (!total) return null;
  const share = (central / total) * 100;
  const parts = [
    { label: `${rubro} (el complejo)`, value: central, color: SERIES[0] },
    { label: "Propios de la Torre 3", value: total - central, color: SERIES[1] },
  ];
  return (
    <div>
      <div className="flex h-4 w-full gap-0.5 overflow-hidden rounded" role="img" aria-label={`${Math.round(share)} % del gasto son gastos centrales del complejo`}>
        {parts.map((p) => (
          <span key={p.label} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} />
        ))}
      </div>
      <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
        {parts.map((p) => (
          <li key={p.label} className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-1.5 text-gray-700">
              <span className="size-2.5 rounded-sm" style={{ background: p.color }} aria-hidden />
              {p.label}
            </span>
            <span className="tabular font-semibold text-gray-900">
              {formatMoney(p.value)} · {Math.round((p.value / total) * 100)} %
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- Obras: approved vs spent vs backed (grouped bar list) -----------------------------------

export function ObrasBars({ obras }: { obras: AsambleaObra[] }) {
  const parts = [
    { key: "aprobado", label: "Aprobado", color: OTHER },
    { key: "gastado", label: "Gastado", color: SERIES[0] },
    { key: "respaldado", label: "Respaldado", color: SERIES[1] },
  ] as const;
  const max = Math.max(1, ...obras.flatMap((o) => [o.aprobado ?? 0, o.gastado]));
  return (
    <div>
      <Legend items={parts.map((p) => ({ label: p.label, color: p.color }))} />
      <ul className="mt-3 space-y-4">
        {obras.map((o) => (
          <li key={o.id}>
            <div className="text-sm font-semibold text-gray-900">{o.nombre}</div>
            <div className="mt-1 space-y-1">
              {parts.map((p) => {
                const v = o[p.key];
                return (
                  <div key={p.key} className="grid grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-2 text-xs">
                    <span className="text-gray-500">{p.label}</span>
                    <span className="h-2 rounded-full bg-gray-100" aria-hidden>
                      {v != null && <span className="block h-2 rounded-full" style={{ width: `${(v / max) * 100}%`, background: p.color }} />}
                    </span>
                    <span className="tabular text-right font-semibold text-gray-900">{v == null ? "sin monto en el acta" : formatMoney(v)}</span>
                  </div>
                );
              })}
            </div>
            {o.criterio && <p className="mt-1 text-xs text-gray-500">Aprobado: {o.criterio}.</p>}
            {o.detalle && <p className="mt-1 text-xs text-gray-700">{o.detalle}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
