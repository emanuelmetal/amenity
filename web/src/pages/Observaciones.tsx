import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { Comments } from "../components/Comments";
import { ReceiptDetail } from "../components/ReceiptDetail";
import { Card, Empty, ErrorBox, Loading, MultiSelect, PageHeader, Select, SidePanel } from "../components/ui";
import { api, type Observation, type ObservationState } from "../lib/api";
import { formatDate, formatMoney, formatPeriod } from "../lib/format";
import { ExpensePanel } from "./Gastos";

const STATE: Record<ObservationState, { label: string; dot: string }> = {
  abierta: { label: "Abierta", dot: "bg-error" },
  enviada: { label: "Enviada a la administración", dot: "bg-warning" },
  respondida: { label: "Respondida", dot: "bg-info" },
  resuelta: { label: "Resuelta", dot: "bg-success" },
  descartada: { label: "Descartada", dot: "bg-gray-400" },
};

function StateTag({ estado }: { estado: ObservationState }) {
  const s = STATE[estado];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-gray-200 bg-white px-2 py-0.5 text-xs font-semibold text-gray-900">
      <span className={`size-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function ObservationCard({ o, onLine, onTicket }: { o: Observation; onLine: (id: number) => void; onTicket: (id: number) => void }) {
  const [showComments, setShowComments] = useState(false);
  return (
    <Card>
      <div className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span className="tabular">{o.id}</span>
              <span className="rounded-md bg-gray-100 px-2 py-0.5 font-medium text-gray-700">{o.tipo}</span>
              <StateTag estado={o.estado} />
              <span>Registrada el {formatDate(o.fecha)}</span>
            </div>
            <h3 className="font-semibold text-gray-900">{o.titulo}</h3>
          </div>
          {o.importe != null && <span className="tabular text-lg font-semibold text-gray-900">{formatMoney(o.importe)}</span>}
        </div>
        <p className="whitespace-pre-line text-sm text-gray-700">{o.detalle}</p>
        {o.lines.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase text-gray-500">Gastos</div>
            <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
              {o.lines.map((l) => (
                <li key={l.id}>
                  <button className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50" onClick={() => onLine(l.id)}>
                    <span className="min-w-0">
                      <span className="block truncate text-gray-900">{l.concepto}{l.detalle ? ` · ${l.detalle}` : ""}</span>
                      <span className="block text-xs text-gray-500">{formatPeriod(l.period_id)} · {l.rubro}</span>
                    </span>
                    <span className="tabular shrink-0 font-medium text-gray-900">{formatMoney(l.importe)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {o.tickets.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase text-gray-500">Comprobantes</div>
            <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
              {o.tickets.map((t) => (
                <li key={t.id}>
                  <button className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50" onClick={() => onTicket(t.id)}>
                    <span className="min-w-0">
                      <span className="block truncate text-gray-900">{t.proveedor ?? "Proveedor sin identificar"}</span>
                      <span className="block truncate text-xs text-gray-500">{[t.fecha && formatDate(t.fecha), t.descripcion].filter(Boolean).join(" · ")}</span>
                    </span>
                    <span className="tabular shrink-0 font-medium text-gray-900">{formatMoney(t.total)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {o.movements.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase text-gray-500">Movimientos bancarios</div>
            <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
              {o.movements.map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate text-gray-900">{m.descripcion}</span>
                    <span className="block text-xs text-gray-500">{formatDate(m.fecha)}</span>
                  </span>
                  <span className="tabular shrink-0 font-medium text-gray-900">{formatMoney(m.importe)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {o.respuesta && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
            <div className="text-xs font-semibold uppercase text-gray-500">
              Respuesta de la administración{o.fecha_respuesta ? ` · ${formatDate(o.fecha_respuesta)}` : ""}
            </div>
            <p className="whitespace-pre-line text-gray-700">{o.respuesta}</p>
          </div>
        )}
        <details onToggle={(e) => setShowComments(e.currentTarget.open)}>
          <summary className="cursor-pointer text-sm text-primary">Comentarios de los vecinos</summary>
          {showComments && <div className="pt-2"><Comments entityType="observation" entityId={o.id} /></div>}
        </details>
      </div>
    </Card>
  );
}

export default function Observaciones() {
  const [params, setParams] = useSearchParams();
  const period = params.getAll("period");
  const estado = params.get("estado") ?? "";
  const [line, setLine] = useState<number | null>(null);
  const [ticket, setTicket] = useState<number | null>(null);
  const set = (k: string, v: string | string[]) => {
    const next = new URLSearchParams(params);
    next.delete(k);
    for (const x of Array.isArray(v) ? v : [v]) if (x) next.append(k, x);
    setParams(next, { replace: true });
  };

  const all = useQuery({ queryKey: ["observations"], queryFn: () => api<Observation[]>("/observations") });
  const rows = (all.data ?? []).filter((o) => (!period.length || period.includes(o.period_id)) && (!estado || o.estado === estado));
  const periodOptions = [...new Set((all.data ?? []).map((o) => o.period_id))]
    .sort()
    .map((p) => ({ value: p, label: formatPeriod(p), group: p.slice(0, 4) }));
  const months = [...new Set(rows.map((o) => o.period_id))].sort().reverse();
  const open = rows.filter((o) => o.estado === "abierta" || o.estado === "enviada" || o.estado === "respondida");
  const atStake = open.reduce((s, o) => s + (o.importe ?? 0), 0);

  return (
    <>
      <PageHeader
        title="Observaciones"
        subtitle="Lo que encontramos al revisar los gastos, comprobantes y pagos contra la rendición de la administración, con su respaldo y su estado."
        actions={
          <>
            <MultiSelect label="Período" allLabel="Todos los períodos" plural="períodos" options={periodOptions} value={period} onChange={(v) => set("period", v)} className="w-48" />
            <Select value={estado} onChange={(e) => set("estado", e.target.value)} aria-label="Estado">
              <option value="">Todos los estados</option>
              {/* Discarded observations are not published. */}
              {Object.entries(STATE).filter(([k]) => k !== "descartada").map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
            </Select>
          </>
        }
      />
      {all.isLoading ? (
        <Loading />
      ) : all.error ? (
        <ErrorBox error={all.error} />
      ) : !rows.length ? (
        <Empty>No hay observaciones con estos filtros.</Empty>
      ) : (
        <div className="space-y-6">
          <p className="text-sm text-gray-700">
            {rows.length} observaciones · {open.length} sin resolver
            {atStake > 0 && <> · <span className="tabular font-semibold text-gray-900">{formatMoney(atStake)}</span> en juego</>}
          </p>
          {months.map((p) => (
            <section key={p} className="space-y-3">
              <h2 className="text-lg font-semibold text-gray-900">{formatPeriod(p)}</h2>
              {rows.filter((o) => o.period_id === p).map((o) => (
                <ObservationCard key={o.id} o={o} onLine={setLine} onTicket={setTicket} />
              ))}
            </section>
          ))}
        </div>
      )}
      <ExpensePanel id={line} onClose={() => setLine(null)} />
      <SidePanel open={ticket !== null} onClose={() => setTicket(null)} title="Comprobante">
        {ticket !== null && <ReceiptDetail id={ticket} />}
      </SidePanel>
    </>
  );
}
