import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Landmark, Paperclip } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Comments } from "../components/Comments";
import { PageViewer } from "../components/PageViewer";
import { kindLabel, linkStatus } from "../components/ReceiptDetail";
import { Button, Card, Empty, ErrorBox, Input, Loading, MultiSelect, PageHeader, SidePanel, StatusTag } from "../components/ui";
import { api, type ExpenseDetail, type ExpensePage, type ExpenseRow, type Period, type Rubro } from "../lib/api";
import { formatDate, formatMoney, formatPeriod } from "../lib/format";

const COLUMNS: { key: string; label: string; right?: boolean }[] = [
  { key: "period", label: "Período" },
  { key: "rubro", label: "Rubro" },
  { key: "concepto", label: "Concepto" },
  { key: "categoria", label: "Categoría" },
  { key: "importe", label: "Importe", right: true },
];

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function ExpensePanel({ id, onClose }: { id: number | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["expense", id], enabled: id !== null, queryFn: () => api<ExpenseDetail>(`/expenses/${id}`) });
  const e = q.data;
  return (
    <SidePanel open={id !== null} onClose={onClose} title="Detalle del gasto">
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {e && (
        <div className="space-y-4">
          <div>
            <div className="text-sm">{formatPeriod(e.period_id)} · {e.rubro}{e.subcategoria ? ` · ${e.subcategoria}` : ""}</div>
            <div className="text-lg font-semibold text-gray-900">{e.concepto}</div>
            {e.detalle && <div className="text-sm">{e.detalle}</div>}
            <div className="tabular text-xl font-semibold text-gray-900">{formatMoney(e.importe)}</div>
            {e.fondo ? (
              <p className="mt-1 text-xs">Pagado del fondo de obra: no forma parte del total de gastos del mes.</p>
            ) : null}
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt>Proveedor</dt>
            <dd className="text-gray-900">{e.proveedor ?? "—"}</dd>
            <dt>Estado</dt>
            <dd><StatusTag status={e.verified ? "verificado" : "sin-verificar"} /></dd>
          </dl>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-gray-900">Comprobantes vinculados</h3>
            {e.tickets.length ? (
              <ul className="divide-y divide-gray-200 text-sm">
                {e.tickets.map((t) => (
                  <li key={t.id} className="flex items-start justify-between gap-3 py-2">
                    <span>
                      <Link className="font-medium text-gray-900 hover:text-primary" to={`/comprobantes?id=${t.id}`}>
                        {t.proveedor ?? "Proveedor sin identificar"}
                      </Link>
                      <span className="block text-xs">
                        {kindLabel(t.kind, t.letra)}{t.fecha ? ` · ${formatDate(t.fecha)}` : ""}{t.descripcion ? ` · ${t.descripcion}` : ""}
                      </span>
                      <span className="mt-1 block"><StatusTag status={linkStatus(t.status, t.score)} /></span>
                    </span>
                    <span className="tabular whitespace-nowrap font-semibold text-gray-900">{formatMoney(t.total)}</span>
                  </li>
                ))}
                {e.tickets.length > 1 && (
                  <li className="flex justify-between py-2 text-xs">
                    <span>Suma de los comprobantes</span>
                    <span className="tabular font-semibold text-gray-900">{formatMoney(e.tickets.reduce((s, t) => s + t.total, 0))}</span>
                  </li>
                )}
              </ul>
            ) : (
              <p className="text-sm text-gray-400">{e.payments.length ? "Sin comprobante vinculado; el pago figura en el resumen bancario." : "Sin comprobante vinculado."}</p>
            )}
          </div>
          {e.payments.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-gray-900">Pagos bancarios</h3>
              <ul className="divide-y divide-gray-200 text-sm">
                {e.payments.map((p) => (
                  <li key={p.id} className="py-2">
                    <div className="flex items-start justify-between gap-3">
                      <span>
                        <span className="block font-medium text-gray-900">
                          {p.kind === "gastos" ? "Comisiones e impuestos del banco"
                            : p.kind === "cheque" ? "Cheque del consorcio, todavía sin debitar"
                            : p.cheque_numero ? "Cheque del consorcio, debitado de la cuenta" : "Pago desde la cuenta del consorcio"}
                        </span>
                        <span className="block text-xs">
                          {formatDate(p.fecha)}{p.banco ? ` · ${p.banco}` : ""} · {p.descripcion}
                        </span>
                        {p.cheque_numero && (
                          <span className="block text-xs">
                            Cheque N° {p.cheque_numero}{p.cheque_fecha_pago ? `, pagadero el ${formatDate(p.cheque_fecha_pago)}` : ""}
                          </span>
                        )}
                        <span className="mt-1 flex flex-wrap items-center gap-2">
                          <StatusTag status={linkStatus(p.status, p.score)} />
                          {p.pages.map((pg, i) => (
                            <Link key={pg.id} className="text-xs text-primary hover:underline" to={`/paginas/${pg.id}`}>
                              {/* A cleared cheque: the statement page, then the cheque's photo. */}
                              {p.kind === "cheque" || (p.cheque_numero && i === p.pages.length - 1 && p.pages.length > 1) ? "Foto del cheque" : "Resumen bancario"}, pág. {pg.page_no}
                            </Link>
                          ))}
                        </span>
                      </span>
                      <span className="tabular whitespace-nowrap font-semibold text-gray-900">{formatMoney(p.importe)}</span>
                    </div>
                    {p.items.length > 0 && (
                      <ul className="mt-2 space-y-1 rounded bg-gray-50 p-2 text-xs">
                        {p.items.map((it) => (
                          <li key={it.descripcion} className="flex justify-between gap-3">
                            <span>{it.descripcion}{it.cantidad > 1 ? ` (×${it.cantidad})` : ""}</span>
                            <span className="tabular">{formatMoney(it.importe)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                    {Math.abs(p.importe - e.importe) > 0.01 && e.payments.length === 1 && (
                      <p className="mt-1 text-xs">Diferencia con el gasto: <span className="tabular">{formatMoney(e.importe - p.importe)}</span></p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {e.actas.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-gray-900">En las actas</h3>
              <ul className="divide-y divide-gray-200 text-sm">
                {e.actas.map((a) => (
                  <li key={a.id} className="py-2">
                    <Link className="font-medium text-gray-900 hover:text-primary" to={`/actas/${a.acta_id}`}>
                      {a.numero ? `Acta ${a.numero}` : "Acta"} · {formatDate(a.fecha)}
                    </Link>
                    <span className="block text-xs">{a.texto}{a.importe != null ? ` · ${formatMoney(a.importe)}` : ""}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <h3 className="mb-2 text-sm font-semibold text-gray-900">Página de la liquidación</h3>
            {e.page_id && e.document_id && e.page_no ? (
              <PageViewer pageId={e.page_id} documentId={e.document_id} pageNo={e.page_no} compact />
            ) : (
              <p className="text-sm text-gray-400">Sin página asociada.</p>
            )}
          </div>
          <Comments entityType="expense" entityId={e.id} />
        </div>
      )}
    </SidePanel>
  );
}

/** A line needs a receipt and a bank payment (each only when that evidence exists for its month). */
function Missing({ row }: { row: ExpenseRow }) {
  return (
    <>
      {row.falta_comprobante ? <StatusTag status="sin-comprobante" label="Falta comprobante" /> : null}
      {row.falta_pago ? <StatusTag status="sin-comprobante" label="Falta pago bancario" /> : null}
    </>
  );
}

export default function Gastos() {
  const [params, setParams] = useSearchParams();
  const period = params.getAll("period");
  const rubro = params.getAll("rubro");
  const sinComprobante = params.get("sin_comprobante") === "1";
  const sort = params.get("sort") ?? "period";
  const dir = params.get("dir") ?? "desc";
  const page = Number(params.get("page") ?? 1);
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text);
  const [selected, setSelected] = useState<number | null>(null);

  const set = (patch: Record<string, string | string[]>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      for (const x of Array.isArray(v) ? v : [v]) if (x) next.append(k, x);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  };
  useEffect(() => {
    if ((params.get("q") ?? "") !== q) set({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api<Period[]>("/periods") });
  const rubros = useQuery({ queryKey: ["rubros"], queryFn: () => api<Rubro[]>("/rubros") });
  // Oldest first, grouped by year (ids are YYYY-MM, so a string sort is chronological).
  const periodOptions = [...(periods.data ?? [])]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((p) => ({ value: p.id, label: formatPeriod(p.id), group: p.id.slice(0, 4) }));
  const rubroOptions = (rubros.data ?? []).map((r) => ({ value: r.rubro, label: r.rubro }));
  const data = useQuery({
    queryKey: ["expenses", period, rubro, q, sort, dir, page, sinComprobante],
    queryFn: () => api<ExpensePage>("/expenses", { period, rubro, q, sort, dir, page, sin_comprobante: sinComprobante ? "1" : "" }),
    placeholderData: keepPreviousData,
  });

  const pages = data.data ? Math.max(1, Math.ceil(data.data.count / data.data.pageSize)) : 1;
  const toggleSort = (key: string) => set({ sort: key, dir: sort === key && dir === "desc" ? "asc" : "desc" });

  return (
    <>
      <PageHeader
        title="Gastos"
        subtitle="Cada línea de las liquidaciones de expensas, con su página original."
        actions={
          <>
            <MultiSelect label="Período" allLabel="Todos los períodos" plural="períodos" options={periodOptions} value={period} onChange={(v) => set({ period: v })} className="w-48" />
            <MultiSelect label="Rubro" allLabel="Todos los rubros" plural="rubros" options={rubroOptions} value={rubro} onChange={(v) => set({ rubro: v })} className="w-56" />
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Concepto, detalle o proveedor…" className="w-56" />
            <label className="inline-flex h-9 items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={sinComprobante} onChange={(e) => set({ sin_comprobante: e.target.checked ? "1" : "" })} className="size-4 accent-[var(--color-primary)]" />
              Sin comprobante o sin pago
            </label>
          </>
        }
      />
      <Card bodyClassName="p-0">
        {data.isLoading ? (
          <Loading />
        ) : data.error ? (
          <div className="p-4"><ErrorBox error={data.error} /></div>
        ) : !data.data?.rows.length ? (
          <Empty>No hay gastos que coincidan con los filtros.</Empty>
        ) : (
          <>
            {/* Phones: stacked list so concepto and importe are always visible. */}
            <ul className="divide-y divide-gray-200 md:hidden">
              {data.data.rows.map((r) => (
                <li key={r.id}>
                  <button className="w-full px-4 py-3 text-left hover:bg-gray-50" onClick={() => setSelected(r.id)}>
                    <div className="flex items-start justify-between gap-3">
                      <span>
                        <span className="block font-medium text-gray-900">{r.concepto}</span>
                        {r.detalle && <span className="block text-xs">{r.detalle}</span>}
                      </span>
                      <span className="tabular whitespace-nowrap font-semibold text-gray-900">{formatMoney(r.importe)}</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-xs">
                      <span>{formatPeriod(r.period_id)} · {r.rubro}{r.tickets ? ` · ${r.tickets} compr.` : ""}{r.pagos ? " · pago bancario" : ""}</span>
                      <span className="flex flex-wrap justify-end gap-1">
                        <Missing row={r} />
                        <StatusTag status={r.verified ? "verificado" : "sin-verificar"} />
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                  <tr>
                    {COLUMNS.map((c) => (
                      <th key={c.key} className={`px-6 py-2 ${c.right ? "text-right" : ""}`}>
                        <button className="inline-flex items-center gap-1 uppercase hover:text-gray-900" onClick={() => toggleSort(c.key)}>
                          {c.label}
                          {sort === c.key && (dir === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                        </button>
                      </th>
                    ))}
                    <th className="px-6 py-2">Estado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {data.data.rows.map((r) => (
                    <tr key={r.id} className="cursor-pointer hover:bg-gray-50" onClick={() => setSelected(r.id)}>
                      <td className="whitespace-nowrap px-6 py-4">{formatPeriod(r.period_id)}</td>
                      <td className="px-6 py-4">{r.rubro}</td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-gray-900">{r.concepto}</div>
                        {r.detalle && <div className="text-xs">{r.detalle}</div>}
                      </td>
                      <td className="px-6 py-4">{r.subcategoria ?? "—"}</td>
                      <td className="tabular whitespace-nowrap px-6 py-4 text-right text-gray-900">{formatMoney(r.importe)}</td>
                      <td className="px-6 py-4">
                        <div className="flex flex-col items-start gap-1">
                          <StatusTag status={r.verified ? "verificado" : "sin-verificar"} />
                          {r.tickets ? (
                            <span className="inline-flex items-center gap-1 text-xs"><Paperclip size={12} aria-hidden />{r.tickets} {r.tickets === 1 ? "comprobante" : "comprobantes"}</span>
                          ) : null}
                          {r.pagos ? (
                            <span className="inline-flex items-center gap-1 text-xs"><Landmark size={12} aria-hidden />Pago bancario</span>
                          ) : null}
                          <Missing row={r} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-200 px-6 py-3 text-sm">
              <span>
                {data.data.count.toLocaleString("es-AR")} líneas · total{" "}
                <span className="tabular font-semibold text-gray-900">{formatMoney(data.data.total)}</span>
                {data.data.fondo_total ? (
                  <>
                    {" "}· Fondo de obra{" "}
                    <span className="tabular font-semibold text-gray-900">{formatMoney(data.data.fondo_total)}</span>
                  </>
                ) : null}
              </span>
              <div className="flex items-center gap-1">
                <Button variant="ghost" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })} aria-label="Anterior"><ChevronLeft size={16} /></Button>
                <span className="tabular text-xs">{page} / {pages}</span>
                <Button variant="ghost" disabled={page >= pages} onClick={() => set({ page: String(page + 1) })} aria-label="Siguiente"><ChevronRight size={16} /></Button>
              </div>
            </div>
          </>
        )}
      </Card>
      <ExpensePanel id={selected} onClose={() => setSelected(null)} />
    </>
  );
}
