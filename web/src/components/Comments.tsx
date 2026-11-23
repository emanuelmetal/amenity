import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Flag, MessageSquare, RotateCcw, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError, api, send, type Comment, type CommentEntity, type Me } from "../lib/api";
import { formatTimestamp } from "../lib/format";
import { Button, ErrorBox, Loading } from "./ui";

export const MAX_BODY = 2000;

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), staleTime: Infinity });
}

const ERRORS: Record<string, string> = {
  rate_limited: "Llegaste al máximo de 10 comentarios por día. Probá mañana.",
  personal_data: "El comentario parece tener un CUIL, DNI o CBU. Sacalo antes de publicar.",
  bad_body: `El comentario tiene que tener entre 1 y ${MAX_BODY} caracteres.`,
  not_found: "Ya no existe lo que estás comentando.",
};

function errorText(e: unknown): string {
  const code = (e as ApiError & { code?: string }).code;
  return (code && ERRORS[code]) || "No se pudo publicar. Probá de nuevo.";
}

/** One comment, with the actions this viewer may take on it. */
export function CommentItem({ c, admin, onChanged }: { c: Comment; admin: boolean; onChanged: () => void }) {
  const [reported, setReported] = useState(false);
  const act = useMutation({
    mutationFn: (a: "delete" | "report" | "hide" | "restore") =>
      a === "delete"
        ? send("DELETE", `/comments/${c.id}`)
        : a === "report"
          ? send("POST", `/comments/${c.id}/report`, {})
          : send("POST", `/comments/${c.id}/moderate`, { action: a }),
    onSuccess: (_, a) => {
      if (a === "report") setReported(true);
      onChanged();
    },
  });
  const run = (a: "delete" | "report" | "hide" | "restore", question?: string) => {
    if (!question || window.confirm(question)) act.mutate(a);
  };
  return (
    <li className={`space-y-1 py-3 ${c.status === "hidden" ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
        <span className="font-semibold text-gray-700">{c.author}</span>
        {c.mine && <span className="rounded-md bg-gray-100 px-1.5 py-0.5 text-gray-700">Vos</span>}
        <span>{formatTimestamp(c.created_at)}</span>
        {c.status === "hidden" && <span className="rounded-md bg-gray-100 px-1.5 py-0.5 font-semibold text-gray-700">Oculto</span>}
        {admin && (c.reports ?? 0) > 0 && <span>{c.reports} denuncias</span>}
      </div>
      <p className="whitespace-pre-line break-words text-sm text-gray-900">{c.body}</p>
      <div className="flex flex-wrap gap-1">
        {c.mine && (
          <Button variant="ghost" className="h-7 px-2 text-xs" disabled={act.isPending} onClick={() => run("delete", "¿Borrar tu comentario?")}>
            <Trash2 size={14} /> Borrar
          </Button>
        )}
        {!c.mine && c.status === "visible" && (
          <Button
            variant="ghost"
            className="h-7 px-2 text-xs"
            disabled={act.isPending || reported}
            onClick={() => run("report", "¿Denunciar este comentario? Con 3 denuncias se oculta hasta que lo revise un moderador.")}
          >
            <Flag size={14} /> {reported ? "Denunciado" : "Denunciar"}
          </Button>
        )}
        {admin && c.status === "visible" && (
          <Button variant="ghost" className="h-7 px-2 text-xs" disabled={act.isPending} onClick={() => run("hide", "¿Ocultar este comentario?")}>
            <EyeOff size={14} /> Ocultar
          </Button>
        )}
        {admin && c.status === "hidden" && (
          <Button variant="ghost" className="h-7 px-2 text-xs" disabled={act.isPending} onClick={() => run("restore")}>
            <RotateCcw size={14} /> Restaurar
          </Button>
        )}
      </div>
      {act.error && <p className="text-xs text-error">No se pudo completar la acción.</p>}
    </li>
  );
}

export function CommentForm({ entityType, entityId, onPosted }: { entityType: CommentEntity; entityId: number | string | null; onPosted: () => void }) {
  const [body, setBody] = useState("");
  const post = useMutation({
    mutationFn: () => send<Comment>("POST", "/comments", { entity_type: entityType, entity_id: entityId, body }),
    onSuccess: () => {
      setBody("");
      onPosted();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (body.trim()) post.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        maxLength={MAX_BODY}
        rows={3}
        placeholder="Escribí un comentario. Se publica como “Vecino/a anónimo/a”."
        aria-label="Comentario"
        className="w-full rounded-lg border border-gray-300 p-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-500">
          Sin insultos ni datos personales. {body.length > MAX_BODY - 200 && `${body.length}/${MAX_BODY}`}
        </span>
        <Button variant="primary" type="submit" disabled={post.isPending || !body.trim()}>
          Publicar
        </Button>
      </div>
      {post.error && <p className="text-xs text-error">{errorText(post.error)}</p>}
    </form>
  );
}

/** The thread of one item (or the general board), with the form to add to it. */
export function Comments({ entityType, entityId, title = "Comentarios" }: { entityType: CommentEntity; entityId: number | string | null; title?: string }) {
  const qc = useQueryClient();
  const me = useMe();
  const key = ["comments", entityType, entityId];
  const q = useQuery({
    queryKey: key,
    queryFn: () => api<Comment[]>("/comments", { entity_type: entityType, entity_id: entityId }),
    staleTime: 30_000,
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["comments", "recent"] });
    qc.invalidateQueries({ queryKey: ["moderation"] });
  };
  const admin = me.data?.kind === "admin";
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
        <MessageSquare size={16} /> {title}
        {q.data && q.data.length > 0 && <span className="font-normal text-gray-500">({q.data.length})</span>}
      </h3>
      {q.isLoading ? (
        <Loading />
      ) : q.error ? (
        <ErrorBox error={q.error} />
      ) : q.data?.length ? (
        <ul className="divide-y divide-gray-100">
          {q.data.map((c) => <CommentItem key={c.id} c={c} admin={admin} onChanged={refresh} />)}
        </ul>
      ) : (
        <p className="text-sm text-gray-400">Todavía no hay comentarios.</p>
      )}
      <CommentForm entityType={entityType} entityId={entityId} onPosted={refresh} />
    </section>
  );
}
