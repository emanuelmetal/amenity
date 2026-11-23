import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { CommentItem, Comments, useMe } from "../components/Comments";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "../components/ui";
import { api, type Comment } from "../lib/api";
import { formatTimestamp } from "../lib/format";

/** Where a comment lives on the site. */
function itemLink(c: Comment): string | null {
  switch (c.entity_type) {
    case "expense":
      return `/gastos?q=${encodeURIComponent((c.label ?? "").split(" · ")[0])}`;
    case "ticket":
      return `/comprobantes?id=${c.entity_id}`;
    case "article":
      return `/reglamento/${c.entity_id}`;
    case "acta":
      return `/actas/${c.entity_id}`;
    case "observation":
      return `/observaciones?period=${String(c.entity_id).slice(0, 7)}`;
    default:
      return null;
  }
}

const ENTITY: Record<Comment["entity_type"], string> = {
  general: "Cartelera",
  expense: "Gasto",
  ticket: "Comprobante",
  article: "Reglamento",
  acta: "Acta",
  observation: "Observación",
};

function Recent() {
  const q = useQuery({ queryKey: ["comments", "recent"], queryFn: () => api<Comment[]>("/comments/recent"), staleTime: 30_000 });
  const rows = (q.data ?? []).filter((c) => c.entity_type !== "general");
  return (
    <Card title="Últimos comentarios en el sitio">
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} />
      ) : !rows.length ? (
        <Empty>Nadie comentó gastos, actas ni artículos todavía.</Empty>
      ) : (
        <ul className="divide-y divide-gray-100">
          {rows.map((c) => {
            const to = itemLink(c);
            return (
              <li key={c.id} className="space-y-1 py-3 first:pt-0">
                <div className="text-xs text-gray-500">
                  {ENTITY[c.entity_type]}
                  {c.label ? <>: {to ? <Link className="text-primary hover:underline" to={to}>{c.label}</Link> : c.label}</> : null}
                  {" · "}{formatTimestamp(c.created_at)}
                </div>
                <p className="line-clamp-3 whitespace-pre-line break-words text-sm text-gray-900">{c.body}</p>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function Moderation() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["moderation"], queryFn: () => api<Comment[]>("/moderation"), staleTime: 0 });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["moderation"] });
    qc.invalidateQueries({ queryKey: ["comments"] });
  };
  return (
    <Card title="Moderación">
      <p className="mb-2 text-sm text-gray-500">
        Comentarios denunciados u ocultos. Con 3 denuncias de dispositivos distintos un comentario se oculta solo hasta que un moderador lo
        revise; después de tu decisión, las denuncias ya no lo ocultan.
      </p>
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} />
      ) : !q.data?.length ? (
        <Empty>No hay nada para revisar.</Empty>
      ) : (
        <ul className="divide-y divide-gray-100">
          {q.data.map((c) => {
            const to = itemLink(c);
            return (
              <li key={c.id}>
                <div className="pt-3 text-xs text-gray-500">
                  {ENTITY[c.entity_type]}
                  {to && <> · <Link className="text-primary hover:underline" to={to}>ver dónde está</Link></>}
                  {c.history?.map((h, i) => (
                    <span key={i}> · {h.action === "hide" ? "Ocultado" : "Restaurado"} por moderador #{h.moderator}, {formatTimestamp(h.at)}</span>
                  ))}
                </div>
                <ul><CommentItem c={c} admin onChanged={refresh} /></ul>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export default function Comentarios() {
  const me = useMe();
  return (
    <>
      <PageHeader
        title="Comentarios"
        subtitle="Cartelera de los vecinos. Todos los comentarios se publican como “Vecino/a anónimo/a”. También podés comentar cada gasto, comprobante, acta, observación o artículo del reglamento."
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_minmax(0,420px)]">
        <div className="space-y-4">
          {me.data?.kind === "admin" && <Moderation />}
          <Card>
            <Comments entityType="general" entityId={null} title="Cartelera" />
          </Card>
        </div>
        <div className="space-y-4">
          <Card title="Reglas">
            <ul className="list-disc space-y-1 pl-5 text-sm text-gray-700">
              <li>Sin insultos ni agresiones.</li>
              <li>No acuses a vecinos con nombre, piso o departamento.</li>
              <li>No publiques datos personales (DNI, CUIL, teléfonos, cuentas bancarias).</li>
              <li>Hasta 10 comentarios por día desde cada dispositivo.</li>
              <li>Cualquiera puede denunciar un comentario; con 3 denuncias se oculta hasta que lo revise un moderador de la comisión.</li>
              <li>Ser anónimo en el sitio no quita la responsabilidad legal de cada persona por lo que escribe.</li>
            </ul>
            <p className="mt-2 text-sm">
              Cómo se protege el anonimato: <Link className="text-primary hover:underline" to="/como-funciona">Cómo funciona</Link>.
            </p>
          </Card>
          <Recent />
        </div>
      </div>
    </>
  );
}
