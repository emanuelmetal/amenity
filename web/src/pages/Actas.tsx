import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { Comments } from "../components/Comments";
import { PageViewer } from "../components/PageViewer";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusTag } from "../components/ui";
import { api, type ActaDetail, type ActaItemKind, type ActaSummary } from "../lib/api";
import { formatDate, formatMoney, formatPeriod } from "../lib/format";
import { ExpensePanel } from "./Gastos";

export const ACTA_TIPO: Record<ActaSummary["tipo"], string> = {
  comision: "Reunión de la comisión",
  asamblea: "Asamblea",
  otro: "Acta",
};
const ITEM_GROUPS: { tipo: ActaItemKind; label: string }[] = [
  { tipo: "decision", label: "Decisiones" },
  { tipo: "tarea", label: "Tareas" },
  { tipo: "tema", label: "Temas tratados" },
];

export const actaTitle = (a: { numero: number | null; fecha: string }) =>
  `${a.numero ? `Acta ${a.numero}` : "Acta"} · ${formatDate(a.fecha)}`;

function ActaList() {
  const q = useQuery({ queryKey: ["actas"], queryFn: () => api<ActaSummary[]>("/actas") });
  const years = [...new Set((q.data ?? []).map((a) => a.fecha.slice(0, 4)))];
  return (
    <>
      <PageHeader
        title="Actas"
        subtitle="Las actas del libro de la comisión, transcriptas: qué se decidió, qué tareas quedaron y con qué gastos se relacionan. Cada una tiene las fotos del libro."
      />
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} />
      ) : !q.data?.length ? (
        <Card><Empty>Todavía no se publicaron actas.</Empty></Card>
      ) : (
        <div className="space-y-6">
          {years.map((y) => (
            <section key={y} className="space-y-3">
              <h2 className="text-lg font-semibold text-gray-900">{y}</h2>
              <ol className="space-y-3 border-l border-gray-200 pl-4">
                {q.data.filter((a) => a.fecha.startsWith(y)).map((a) => {
                  const decisions = a.items.filter((i) => i.tipo === "decision");
                  return (
                    <li key={a.id} className="relative">
                      <span className="absolute top-5 -left-[21px] size-2.5 rounded-full border-2 border-white bg-primary" />
                      <Link to={`/actas/${a.id}`} className="block rounded-lg border border-gray-200 bg-white p-4 hover:border-gray-300 hover:bg-gray-50">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                          <span>{ACTA_TIPO[a.tipo]}</span>
                          <StatusTag status={a.verified ? "verificado" : "sin-verificar"} />
                        </div>
                        <div className="mt-1 font-semibold text-gray-900">{actaTitle(a)}</div>
                        <p className="mt-1 line-clamp-2 text-sm text-gray-700">{a.resumen}</p>
                        {decisions.length > 0 && (
                          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-gray-700">
                            {decisions.slice(0, 3).map((d) => <li key={d.id}>{d.texto}</li>)}
                            {decisions.length > 3 && <li className="list-none text-xs text-gray-500">y {decisions.length - 3} decisiones más</li>}
                          </ul>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function ActaView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["acta", id], queryFn: () => api<ActaDetail>(`/actas/${id}`) });
  const [folio, setFolio] = useState(0);
  const [line, setLine] = useState<number | null>(null);
  const a = q.data;
  if (q.isLoading) return <Loading />;
  if (q.error || !a) return <ErrorBox error={q.error} />;
  const page = a.pages[folio] ?? a.pages[0];
  return (
    <>
      <Link to="/actas" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft size={16} /> Todas las actas
      </Link>
      <PageHeader title={actaTitle(a)} subtitle={ACTA_TIPO[a.tipo]} actions={<StatusTag status={a.verified ? "verificado" : "sin-verificar"} />} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_minmax(0,460px)]">
        <div className="space-y-4">
          <Card title="Resumen">
            <p className="whitespace-pre-line text-sm text-gray-700">{a.resumen}</p>
            {a.asistentes.length > 0 && (
              <p className="mt-3 text-sm text-gray-500">Presentes: {a.asistentes.join(", ")}.</p>
            )}
          </Card>
          {ITEM_GROUPS.map(({ tipo, label }) => {
            const items = a.items.filter((i) => i.tipo === tipo);
            if (!items.length) return null;
            return (
              <Card key={tipo} title={label}>
                <ul className="divide-y divide-gray-100">
                  {items.map((it) => (
                    <li key={it.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                      <div className="flex items-start justify-between gap-3">
                        <p className="text-sm text-gray-900">{it.texto}</p>
                        {it.importe != null && <span className="tabular shrink-0 font-semibold text-gray-900">{formatMoney(it.importe)}</span>}
                      </div>
                      {it.period_id && <div className="text-xs text-gray-500">Sobre {formatPeriod(it.period_id)}</div>}
                      {it.gastos.length > 0 && (
                        <ul className="divide-y divide-gray-100 rounded-lg border border-gray-200">
                          {it.gastos.map((g) => (
                            <li key={g.id}>
                              <button className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-gray-50" onClick={() => setLine(g.id)}>
                                <span className="min-w-0">
                                  <span className="block truncate text-gray-900">{g.concepto}{g.detalle ? ` · ${g.detalle}` : ""}</span>
                                  <span className="block text-xs text-gray-500">Gasto de {formatPeriod(g.period_id)} · {g.rubro}</span>
                                </span>
                                <span className="tabular shrink-0 font-medium text-gray-900">{formatMoney(g.importe)}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                      {it.observaciones.map((o) => (
                        <Link key={o.id} to={`/observaciones?period=${o.id.slice(0, 7)}`} className="block text-xs text-primary hover:underline">
                          Observación {o.id}: {o.titulo}
                        </Link>
                      ))}
                    </li>
                  ))}
                </ul>
              </Card>
            );
          })}
          <Card>
            <Comments entityType="acta" entityId={a.id} />
          </Card>
        </div>
        <Card
          title="Libro de actas"
          actions={
            a.pages.length > 1 ? (
              <div className="flex flex-wrap gap-1">
                {a.pages.map((p, i) => (
                  <button
                    key={p.id}
                    onClick={() => setFolio(i)}
                    aria-pressed={i === folio}
                    className={`rounded-md border px-2 py-0.5 text-xs ${i === folio ? "border-primary text-primary" : "border-gray-200"}`}
                  >
                    Foto {i + 1}
                  </button>
                ))}
              </div>
            ) : undefined
          }
        >
          {page ? (
            <PageViewer key={page.id} pageId={page.id} documentId={page.document_id} pageNo={page.page_no} compact />
          ) : (
            <p className="text-sm text-gray-400">Las fotos de esta acta todavía no están publicadas.</p>
          )}
        </Card>
      </div>
      <ExpensePanel id={line} onClose={() => setLine(null)} />
    </>
  );
}

export default function Actas() {
  const { id } = useParams();
  return id ? <ActaView key={id} id={id} /> : <ActaList />;
}
