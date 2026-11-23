import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Button, Card, Empty, Loading, PageHeader } from "../components/ui";
import { ApiError, api, send, type AskAnswer, type AskStatus } from "../lib/api";
import { formatDate, formatMoney, formatPeriod } from "../lib/format";

const EXAMPLES = [
  "¿Cuánto se gastó en taxis del encargado por mes?",
  "¿Cuáles fueron los 10 gastos más grandes de 2026?",
  "¿Cuánto se pagó de honorarios de administración por mes?",
  "¿Qué gastos de 2026 no tienen comprobante?",
  "¿Cuántas observaciones hay abiertas y por cuánto dinero?",
  "¿Qué decidió la comisión sobre la impermeabilización?",
];

const MONEY = /importe|total|monto|saldo|ingreso|egreso|promedio|gasto|pagado|suma/i;
const FLAG = /^(verificad[oa]|respaldado|con_comprobante|con_pago|fondo_reserva|hay_.*)$/;

function cell(col: string, v: string | number | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (FLAG.test(col) && (v === 0 || v === 1)) return v ? "Sí" : "No";
    if (MONEY.test(col)) return formatMoney(v);
    return Number.isInteger(v) ? String(v) : v.toLocaleString("es-AR", { maximumFractionDigits: 2 });
  }
  if (/^\d{4}-\d{2}$/.test(v)) return formatPeriod(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return formatDate(v);
  return v;
}

const label = (col: string) => {
  const s = col.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

const ERRORS: Record<string, string> = {
  rate_limited: "Llegaste al límite de preguntas de hoy. Volvé a intentar mañana.",
  global_limit: "El portal llegó al límite de preguntas de hoy. Volvé a intentar mañana.",
  unavailable: "Las preguntas no están disponibles en este momento.",
  too_long: "La pregunta es demasiado larga (máximo 300 caracteres).",
  failed: "No se pudo responder. Probá de nuevo en un rato.",
};

function errorText(e: unknown): string {
  const err = e as ApiError & { code?: string; data?: { mensaje?: string } };
  if (err.code === "cannot_answer") return err.data?.mensaje || "No encontré cómo responder esa pregunta.";
  return (err.code && ERRORS[err.code]) || "No se pudo responder. Probá de nuevo.";
}

export default function Preguntar() {
  const [text, setText] = useState("");
  const [asked, setAsked] = useState("");
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["ask-status"], queryFn: () => api<AskStatus>("/ask"), staleTime: 0 });
  const ask = useMutation({
    mutationFn: (pregunta: string) => send<AskAnswer>("POST", "/ask", { pregunta }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["ask-status"] }),
  });
  const submit = (q: string) => {
    const p = q.trim();
    if (!p || ask.isPending) return;
    setText(p);
    setAsked(p);
    ask.mutate(p);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(text);
  };
  const disabled = status.data ? !status.data.available || status.data.remaining === 0 : false;
  const a = ask.data;

  return (
    <>
      <PageHeader
        title="Preguntale al portal"
        subtitle="Escribí una pregunta sobre gastos, comprobantes, pagos, actas u observaciones. Un modelo de IA la traduce a una consulta sobre los datos publicados."
      />
      <Card>
        <form onSubmit={onSubmit} className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(text);
              }
            }}
            maxLength={300}
            rows={2}
            placeholder="Ej.: ¿Cuánto se gastó en limpieza en 2026?"
            className="w-full resize-y rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-xs placeholder:text-gray-400 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            disabled={disabled}
            aria-label="Pregunta"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-gray-500">
              {status.data && !status.data.available
                ? ERRORS.unavailable
                : status.data
                  ? `Te quedan ${status.data.remaining} de ${status.data.limit} preguntas hoy.`
                  : null}
            </span>
            <Button variant="primary" type="submit" disabled={disabled || ask.isPending || !text.trim()}>
              <Sparkles size={16} /> {ask.isPending ? "Pensando…" : "Preguntar"}
            </Button>
          </div>
        </form>
        {!asked && (
          <div className="mt-4 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => submit(ex)}
                disabled={disabled}
                className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-left text-xs text-gray-700 hover:border-gray-300 hover:bg-gray-100 disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
        )}
      </Card>

      {ask.isPending ? (
        <Loading />
      ) : ask.error ? (
        <Card>
          <p className="text-sm text-gray-700">{errorText(ask.error)}</p>
          <p className="mt-2 text-sm text-gray-500">
            También podés <Link className="text-primary hover:underline" to={`/buscar?q=${encodeURIComponent(asked)}`}>buscar el texto en los documentos</Link> o
            revisar <Link className="text-primary hover:underline" to="/analisis">Análisis</Link>.
          </p>
        </Card>
      ) : a ? (
        <Card title={a.titulo} bodyClassName="p-0">
          <p className="px-4 pb-3 text-sm text-gray-500">“{asked}”</p>
          {!a.rows.length ? (
            <Empty>La consulta no devolvió resultados.</Empty>
          ) : (
            <div className="overflow-x-auto border-t border-gray-200">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {a.columns.map((c, i) => (
                      <th key={i} className={`whitespace-nowrap px-4 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500 ${typeof a.rows[0][i] === "number" ? "text-right" : "text-left"}`}>
                        {label(c)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {a.rows.map((r, j) => (
                    <tr key={j}>
                      {r.map((v, i) => (
                        <td key={i} className={`px-4 py-2 align-top text-gray-900 ${typeof v === "number" ? "tabular whitespace-nowrap text-right" : ""}`}>
                          {cell(a.columns[i], v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="space-y-2 border-t border-gray-200 px-4 py-3 text-xs text-gray-500">
            {a.truncated && <p>Se muestran las primeras {a.rows.length} filas.</p>}
            <p>
              Respuesta generada automáticamente: el modelo puede interpretar mal la pregunta. Revisá la consulta y
              confirmá los números en <Link className="text-primary hover:underline" to="/gastos">Gastos</Link> o{" "}
              <Link className="text-primary hover:underline" to="/analisis">Análisis</Link>.
            </p>
            <details>
              <summary className="inline-flex cursor-pointer items-center gap-1 text-gray-700"><Code size={14} /> Ver la consulta SQL</summary>
              <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 font-mono text-xs text-gray-800">{a.sql}</pre>
            </details>
          </div>
        </Card>
      ) : null}
    </>
  );
}
