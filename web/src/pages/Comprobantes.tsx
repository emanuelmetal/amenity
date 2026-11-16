import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { kindLabel, ReceiptDetail } from "../components/ReceiptDetail";
import { Button, Card, Empty, ErrorBox, Input, Loading, MultiSelect, PageHeader, Select, SidePanel, StatusTag } from "../components/ui";
import { api, pageImageUrl, type Period, type TicketPage } from "../lib/api";
import { formatDate, formatMoney, formatPeriod, TICKET_KIND_LABEL } from "../lib/format";

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function Comprobantes() {
  const [params, setParams] = useSearchParams();
  const period = params.getAll("period");
  const kind = params.get("kind") ?? "";
  const linked = params.get("linked") ?? "";
  const page = Number(params.get("page") ?? 1);
  const selected = params.get("id") ? Number(params.get("id")) : null;
  const [text, setText] = useState(params.get("q") ?? "");
  const q = useDebounced(text);

  const set = (patch: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      for (const x of Array.isArray(v) ? v : [v]) if (x) next.append(k, x);
    }
    if (!("page" in patch) && !("id" in patch)) next.delete("page");
    setParams(next, { replace: !("id" in patch) });
  };
  useEffect(() => {
    if ((params.get("q") ?? "") !== q) set({ q });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api<Period[]>("/periods") });
  const data = useQuery({
    queryKey: ["tickets", period, kind, linked, q, page],
    queryFn: () => api<TicketPage>("/tickets", { period, kind, linked, q, page }),
    placeholderData: keepPreviousData,
  });
  const periodOptions = [...(periods.data ?? [])]
    .sort((a, b) => a.id.localeCompare(b.id))
    .map((p) => ({ value: p.id, label: formatPeriod(p.id), group: p.id.slice(0, 4) }));
  const pages = data.data ? Math.max(1, Math.ceil(data.data.count / data.data.pageSize)) : 1;

  return (
    <>
      <PageHeader
        title="Comprobantes"
        subtitle="Facturas, recibos y tickets que entregó la administración, vinculados a cada gasto."
        actions={
          <>
            <MultiSelect label="Período" allLabel="Todos los períodos" plural="períodos" options={periodOptions} value={period} onChange={(v) => set({ period: v })} className="w-48" />
            <Select value={kind} onChange={(e) => set({ kind: e.target.value })} aria-label="Tipo">
              <option value="">Todos los tipos</option>
              {Object.entries(TICKET_KIND_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </Select>
            <Select value={linked} onChange={(e) => set({ linked: e.target.value })} aria-label="Vinculación">
              <option value="">Vinculados y sin vincular</option>
              <option value="1">Vinculados a un gasto</option>
              <option value="0">Sin vincular</option>
            </Select>
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Proveedor o descripción…" className="w-56" />
          </>
        }
      />
      <Card bodyClassName="p-0">
        {data.isLoading ? (
          <Loading />
        ) : data.error ? (
          <div className="p-4"><ErrorBox error={data.error} /></div>
        ) : !data.data?.rows.length ? (
          <Empty>No hay comprobantes que coincidan con los filtros.</Empty>
        ) : (
          <>
            <ul className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 xl:grid-cols-3">
              {data.data.rows.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => set({ id: String(t.id) })}
                    className={`flex w-full gap-3 rounded-lg border p-3 text-left hover:bg-gray-50 ${t.linked ? "border-gray-200" : "border-warning"}`}
                  >
                    <span className="grid h-24 w-20 shrink-0 place-items-center overflow-hidden rounded-md border border-gray-200 bg-gray-50">
                      {t.page_id ? (
                        <img src={pageImageUrl(t.page_id)} alt="" loading="lazy" className="h-full w-full object-cover object-top" />
                      ) : (
                        <FileText size={20} className="text-gray-400" aria-hidden />
                      )}
                    </span>
                    <span className="min-w-0 flex-1 space-y-1">
                      <span className="block truncate font-medium text-gray-900">{t.proveedor ?? "Proveedor sin identificar"}</span>
                      {t.descripcion && <span className="line-clamp-2 block text-xs">{t.descripcion}</span>}
                      <span className="block text-xs">{kindLabel(t.kind, t.letra)} · {t.fecha ? formatDate(t.fecha) : formatPeriod(t.period_id)}</span>
                      <span className="flex flex-wrap items-center justify-between gap-2">
                        <span className="tabular font-semibold text-gray-900">{formatMoney(t.total)}</span>
                        {t.linked ? <StatusTag status={t.verified ? "verificado" : "sin-verificar"} /> : <StatusTag status="sin-comprobante" label="Sin gasto vinculado" />}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-200 px-6 py-3 text-sm">
              <span>
                {data.data.count.toLocaleString("es-AR")} comprobantes · total{" "}
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
      <SidePanel open={selected !== null} onClose={() => set({ id: null })} title="Comprobante">
        {selected !== null && <ReceiptDetail id={selected} />}
      </SidePanel>
    </>
  );
}
