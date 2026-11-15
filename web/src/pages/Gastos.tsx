import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { PageViewer } from "../components/PageViewer";
import { Button, Card, Empty, ErrorBox, Input, Loading, PageHeader, Select, SidePanel, StatusTag } from "../components/ui";
import { api, type ExpenseDetail, type ExpensePage, type Period, type Rubro } from "../lib/api";
import { formatMoney, formatPeriod } from "../lib/format";

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

function ExpensePanel({ id, onClose }: { id: number | null; onClose: () => void }) {
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
          </div>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt>Proveedor</dt>
            <dd className="text-gray-900">{e.proveedor ?? "—"}</dd>
            <dt>Estado</dt>
            <dd><StatusTag status={e.verified ? "verificado" : "sin-verificar"} /></dd>
          </dl>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-gray-900">Comprobantes vinculados</h3>
            <p className="text-sm text-gray-400">La vinculación con tickets y facturas llega en la próxima etapa.</p>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-gray-900">Página de la liquidación</h3>
            {e.page_id && e.document_id && e.page_no ? (
              <PageViewer pageId={e.page_id} documentId={e.document_id} pageNo={e.page_no} compact />
            ) : (
              <p className="text-sm text-gray-400">Sin página asociada.</p>
            )}
          </div>
        </div>
      )}
    </SidePanel>
  );
}

export default function Gastos() {
  const [params, setParams] = useSearchParams();
  const period = params.get("period") ?? "";
  const rubro = params.get("rubro") ?? "";
  const sort = params.get("sort") ?? "period";
  const dir = params.get("dir") ?? "desc";
  const page = Number(params.get("page") ?? 1);
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text);
  const [selected, setSelected] = useState<number | null>(null);

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) v ? next.set(k, v) : next.delete(k);
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  };
  useEffect(() => {
    if ((params.get("q") ?? "") !== q) set({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api<Period[]>("/periods") });
  const rubros = useQuery({ queryKey: ["rubros"], queryFn: () => api<Rubro[]>("/rubros") });
  const data = useQuery({
    queryKey: ["expenses", period, rubro, q, sort, dir, page],
    queryFn: () => api<ExpensePage>("/expenses", { period, rubro, q, sort, dir, page }),
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
            <Select value={period} onChange={(e) => set({ period: e.target.value })} aria-label="Período">
              <option value="">Todos los períodos</option>
              {periods.data?.map((p) => <option key={p.id} value={p.id}>{formatPeriod(p.id)}</option>)}
            </Select>
            <Select value={rubro} onChange={(e) => set({ rubro: e.target.value })} aria-label="Rubro">
              <option value="">Todos los rubros</option>
              {rubros.data?.map((r) => <option key={r.rubro} value={r.rubro}>{r.rubro}</option>)}
            </Select>
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Concepto, detalle o proveedor…" className="w-56" />
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
                      <span>{formatPeriod(r.period_id)} · {r.rubro}</span>
                      <StatusTag status={r.verified ? "verificado" : "sin-verificar"} />
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
                      <td className="px-6 py-4"><StatusTag status={r.verified ? "verificado" : "sin-verificar"} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-200 px-6 py-3 text-sm">
              <span>
                {data.data.count.toLocaleString("es-AR")} líneas · total{" "}
                <span className="tabular font-semibold text-gray-900">{formatMoney(data.data.total)}</span>
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
