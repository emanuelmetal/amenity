import { useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import type { MonthlyStat, RubroStat, VendorStat } from "../lib/api";
import { formatMoney, formatMoneyShort, formatPeriod, formatPeriodShort } from "../lib/format";

/*
 * Series colours: the design system's five chart hues (design/theme.css) in an order
 * validated for colour-vision deficiency (dataviz validate_palette.js, light surface:
 * worst adjacent CVD ΔE 21.6, normal-vision 29.1). The original order put blue next to
 * violet (ΔE 2.0 for protan viewers). Three hues are below 3:1 contrast on white, so every
 * chart also carries a legend with names, direct labels or values, and a table view.
 */
export const SERIES = ["#286cf0", "#00c27f", "#8c62ff", "#f59e0b", "#05aed3"] as const;
export const OTHER = "#a4a7ae"; // "Otros" (folded series), gray-400
export const GRID = "#e5e5e5"; // gray-200
export const AXIS = "#717680"; // gray-500

export const axisProps = { tick: { fill: AXIS, fontSize: 12 }, tickLine: false, axisLine: false } as const;

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-700">
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: i.color }} aria-hidden />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

export function TooltipBox({
  title,
  rows,
  format = formatMoney,
}: {
  title: string;
  rows: { label: string; value: number; color: string }[];
  format?: (n: number) => string;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-gray-900">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5 text-gray-700">
            <span className="size-2 rounded-sm" style={{ background: r.color }} aria-hidden />
            {r.label}
          </span>
          <span className="tabular font-semibold text-gray-900">{format(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

/** "Ver tabla": the same numbers as a table (accessibility, and the contrast relief rule). */
export function TableView({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2 print:hidden">
      <button className="text-xs font-medium text-primary hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {open ? "Ocultar tabla" : "Ver tabla"}
      </button>
      {open && <div className="mt-2 overflow-x-auto">{children}</div>}
    </div>
  );
}

export const th = "px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wider text-gray-500";
export const td = "tabular px-3 py-1.5 text-right";

// ---- Ingresos vs Gastos ------------------------------------------------------------------

export function IncomeVsSpendChart({ data }: { data: MonthlyStat[] }) {
  const rows = data.map((d) => ({ period: d.id, Gastos: d.gastos, Ingresos: d.ingresos ?? null }));
  const series = [
    { key: "Gastos", color: SERIES[0] },
    { key: "Ingresos", color: SERIES[1] },
  ] as const;
  const last = rows.length - 1;
  const endLabel = (key: "Gastos" | "Ingresos", color: string) =>
    function EndLabel(props: { x?: number | string; y?: number | string; index?: number }) {
      if (props.index !== last || props.x == null || props.y == null) return null;
      return (
        <text x={Number(props.x) + 6} y={Number(props.y)} dy={4} fontSize={12} fill="#404040">
          <tspan fill={color} aria-hidden>
            ●{" "}
          </tspan>
          {key}
        </text>
      );
    };
  return (
    <div>
      <Legend items={series.map((s) => ({ label: s.key, color: s.color }))} />
      <div className="mt-2 h-64" role="img" aria-label="Ingresos y gastos por período">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 72, bottom: 0, left: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="4 4" />
            <XAxis dataKey="period" tickFormatter={formatPeriodShort} {...axisProps} />
            <YAxis tickFormatter={formatMoneyShort} width={72} {...axisProps} />
            <Tooltip
              cursor={{ stroke: AXIS, strokeDasharray: "3 3" }}
              content={(p: TooltipContentProps<ValueType, NameType>) =>
                p.active && p.payload?.length ? (
                  <TooltipBox
                    title={formatPeriod(String(p.label))}
                    rows={series
                      .map((s) => ({ label: s.key, value: Number(p.payload.find((x) => x.dataKey === s.key)?.value), color: s.color }))
                      .filter((r) => Number.isFinite(r.value))}
                  />
                ) : null
              }
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stroke={s.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                connectNulls
                label={endLabel(s.key, s.color)}
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
              <th className={th}>Período</th>
              <th className={`${th} text-right`}>Ingresos</th>
              <th className={`${th} text-right`}>Gastos</th>
              <th className={`${th} text-right`}>Saldo al cierre</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {data.map((d) => (
              <tr key={d.id}>
                <td className="px-3 py-1.5">{formatPeriod(d.id)}</td>
                <td className={td}>{formatMoney(d.ingresos)}</td>
                <td className={td}>{formatMoney(d.gastos)}</td>
                <td className={td}>{formatMoney(d.saldo_final)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

// ---- Gasto por rubro (stacked bars) ----------------------------------------------------------

/** Top rubros keep a hue (fixed by overall size, so a filter never repaints them); the rest fold into "Otros". */
export function rubroColors(stats: RubroStat[]): Map<string, string> {
  const totals = new Map<string, number>();
  for (const s of stats) totals.set(s.rubro, (totals.get(s.rubro) ?? 0) + s.total);
  const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([r]) => r);
  const m = new Map<string, string>();
  ranked.forEach((r, i) => m.set(r, i < SERIES.length - 1 ? SERIES[i] : OTHER));
  if (ranked.length === SERIES.length) m.set(ranked[SERIES.length - 1], SERIES[SERIES.length - 1]);
  return m;
}

export function SpendByRubroChart({ stats }: { stats: RubroStat[] }) {
  const colors = rubroColors(stats);
  const named = [...colors.entries()].filter(([, c]) => c !== OTHER).map(([r]) => r);
  const keys = [...named, ...(named.length < colors.size ? ["Otros"] : [])];
  const colorOf = (k: string) => (k === "Otros" ? OTHER : colors.get(k)!);
  const periods = [...new Set(stats.map((s) => s.period))].sort();
  const rows = periods.map((period) => {
    const row: Record<string, number | string> = { period };
    for (const k of keys) row[k] = 0;
    for (const s of stats.filter((x) => x.period === period)) {
      const k = named.includes(s.rubro) ? s.rubro : "Otros";
      row[k] = (row[k] as number) + s.total;
    }
    return row;
  });
  return (
    <div>
      <Legend items={keys.map((k) => ({ label: k, color: colorOf(k) }))} />
      <div className="mt-2 h-72" role="img" aria-label="Gasto por rubro y período">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }} barCategoryGap="25%">
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="4 4" />
            <XAxis dataKey="period" tickFormatter={formatPeriodShort} {...axisProps} />
            <YAxis tickFormatter={formatMoneyShort} width={72} {...axisProps} />
            <Tooltip
              cursor={{ fill: "#f5f5f5" }}
              content={(p: TooltipContentProps<ValueType, NameType>) =>
                p.active && p.payload?.length ? (
                  <TooltipBox
                    title={formatPeriod(String(p.label))}
                    rows={[...p.payload].reverse().map((x) => ({ label: String(x.dataKey), value: Number(x.value), color: colorOf(String(x.dataKey)) }))}
                  />
                ) : null
              }
            />
            {keys.map((k, i) => (
              <Bar
                key={k}
                dataKey={k}
                stackId="rubros"
                fill={colorOf(k)}
                stroke="#fff"
                strokeWidth={2} // 2px surface gap between stacked segments
                radius={i === keys.length - 1 ? [4, 4, 0, 0] : 0}
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
              <th className={th}>Período</th>
              {keys.map((k) => (
                <th key={k} className={`${th} text-right`}>{k}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rows.map((r) => (
              <tr key={String(r.period)}>
                <td className="whitespace-nowrap px-3 py-1.5">{formatPeriod(String(r.period))}</td>
                {keys.map((k) => (
                  <td key={k} className={td}>{formatMoney(Number(r[k]))}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableView>
    </div>
  );
}

// ---- Top proveedores (ranked bar list, one series) ------------------------------------------

export function TopVendors({ data }: { data: VendorStat[] }) {
  const max = Math.max(...data.map((d) => d.total), 1);
  return (
    <ul className="space-y-2.5">
      {data.map((d) => (
        <li key={d.proveedor} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
          <span className="truncate text-gray-900" title={d.proveedor}>{d.proveedor}</span>
          <span className="tabular text-right font-semibold text-gray-900">{formatMoney(d.total)}</span>
          <span className="col-span-2 h-2 rounded-full bg-gray-100" aria-hidden>
            <span className="block h-2 rounded-full" style={{ width: `${(d.total / max) * 100}%`, background: SERIES[0] }} />
          </span>
          <span className="col-span-2 text-xs text-gray-500">{d.comprobantes} {d.comprobantes === 1 ? "comprobante" : "comprobantes"}</span>
        </li>
      ))}
    </ul>
  );
}
