import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api, type TicketDetail } from "../lib/api";
import { formatDate, formatMoney, formatPeriod, TICKET_KIND_LABEL } from "../lib/format";
import { Comments } from "./Comments";
import { PageViewer } from "./PageViewer";
import { ErrorBox, Loading, StatusTag } from "./ui";

export function kindLabel(kind: string, letra: string | null): string {
  return `${TICKET_KIND_LABEL[kind] ?? kind}${letra ? ` ${letra}` : ""}`;
}

/** Status of an expense <-> receipt link as shown to neighbours. */
export function linkStatus(status: string, score: number): "verificado" | "auto" | "posible" {
  if (status === "verified") return "verificado";
  return score >= 0.9 ? "auto" : "posible";
}

export function ReceiptDetail({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api<TicketDetail>(`/tickets/${id}`) });
  const [pageIdx, setPageIdx] = useState(0);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const t = q.data!;
  const page = t.pages[Math.min(pageIdx, t.pages.length - 1)];
  const number = t.pto_vta != null && t.nro_cmp != null ? `${String(t.pto_vta).padStart(4, "0")}-${String(t.nro_cmp).padStart(8, "0")}` : null;
  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm">
          {kindLabel(t.kind, t.letra)}
          {number ? ` N° ${number}` : ""} · {t.fecha ? formatDate(t.fecha) : "sin fecha"}
        </div>
        <div className="text-lg font-semibold text-gray-900">{t.proveedor ?? "Proveedor sin identificar"}</div>
        {t.descripcion && <div className="text-sm">{t.descripcion}</div>}
        <div className="tabular text-xl font-semibold text-gray-900">{formatMoney(t.total)}</div>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <dt>Estado</dt>
        <dd><StatusTag status={t.verified ? "verificado" : "sin-verificar"} /></dd>
        <dt>Origen de los datos</dt>
        <dd className="text-gray-900">{t.source === "qr" ? "Código QR de ARCA (exacto)" : "Transcripción de la imagen"}</dd>
        {t.cuit && (
          <>
            <dt>CUIT</dt>
            <dd className="text-gray-900">{t.cuit}</dd>
          </>
        )}
        {t.cae && (
          <>
            <dt>CAE</dt>
            <dd className="tabular text-gray-900">{t.cae}</dd>
          </>
        )}
        {t.medio_pago && (
          <>
            <dt>Medio de pago</dt>
            <dd className="text-gray-900">{t.medio_pago}</dd>
          </>
        )}
        <dt>Período</dt>
        <dd className="text-gray-900">{formatPeriod(t.period_id)}</dd>
      </dl>

      {t.items.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-900">Detalle</h3>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-gray-200">
              {t.items.map((it, i) => (
                <tr key={i}>
                  <td className="py-1.5 pr-2">{it.cantidad != null ? `${it.cantidad.toLocaleString("es-AR")} × ` : ""}{it.descripcion}</td>
                  <td className="tabular py-1.5 text-right text-gray-900">{formatMoney(it.importe)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-gray-900">Gastos que justifica</h3>
        {t.lines.length ? (
          <ul className="divide-y divide-gray-200 text-sm">
            {t.lines.map((l) => (
              <li key={l.id} className="flex items-start justify-between gap-3 py-2">
                <span>
                  <Link className="font-medium text-gray-900 hover:text-primary" to={`/gastos?period=${l.period_id}&q=${encodeURIComponent(l.concepto)}`}>
                    {l.concepto}
                  </Link>
                  {l.detalle && <span className="block text-xs">{l.detalle}</span>}
                  <span className="mt-1 flex items-center gap-2 text-xs">
                    {formatPeriod(l.period_id)} · {l.rubro} <StatusTag status={linkStatus(l.status, l.score)} />
                  </span>
                </span>
                <span className="tabular whitespace-nowrap font-semibold text-gray-900">{formatMoney(l.importe)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-400">No está vinculado a ningún gasto de la liquidación.</p>
        )}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-gray-900">Imagen del comprobante</h3>
          {t.pages.length > 1 && (
            <div className="flex gap-1">
              {t.pages.map((p, i) => (
                <button
                  key={p.id}
                  onClick={() => setPageIdx(i)}
                  className={`rounded-md border px-2 py-0.5 text-xs ${i === pageIdx ? "border-primary text-primary" : "border-gray-200"}`}
                  aria-pressed={i === pageIdx}
                >
                  Pág. {p.page_no}
                </button>
              ))}
            </div>
          )}
        </div>
        {page ? (
          <PageViewer key={page.id} pageId={page.id} documentId={page.document_id} pageNo={page.page_no} compact />
        ) : (
          <p className="text-sm text-gray-400">La imagen no se publica por privacidad.</p>
        )}
      </div>
      <Comments entityType="ticket" entityId={t.id} />
    </div>
  );
}
