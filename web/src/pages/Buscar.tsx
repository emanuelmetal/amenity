import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText, NotebookPen, Paperclip, Receipt } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";
import { Button, Card, Empty, ErrorBox, Input, Loading, PageHeader, Snippet } from "../components/ui";
import { api, type SearchHit } from "../lib/api";

function hitLink(h: SearchHit): string {
  if (h.entity_type === "article") return `/reglamento/${h.entity_id}`;
  if (h.entity_type === "expense") return `/gastos?q=${encodeURIComponent(h.title)}`;
  if (h.entity_type === "ticket") return `/comprobantes?id=${h.entity_id}`;
  if (h.entity_type === "acta") return `/actas/${h.entity_id}`;
  return h.page_id ? `/paginas/${h.page_id}` : "#";
}

const ICON = { article: <BookOpen size={16} />, expense: <Receipt size={16} />, ticket: <Paperclip size={16} />, page: <FileText size={16} />, acta: <NotebookPen size={16} /> };
const KIND = { article: "Reglamento", expense: "Gasto", ticket: "Comprobante", page: "Documento", acta: "Acta" };

export default function Buscar() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  useEffect(() => setText(q), [q]);
  const hits = useQuery({ queryKey: ["search", q], enabled: q.trim().length > 0, queryFn: () => api<SearchHit[]>("/search", { q }) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(text.trim() ? { q: text.trim() } : {});
  };
  return (
    <>
      <PageHeader title="Buscar" subtitle="En el reglamento, las liquidaciones, los comprobantes, las actas y sus páginas." />
      <form onSubmit={submit} className="flex max-w-xl gap-2">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ej.: mascotas, pintura, ascensor" className="flex-1" autoFocus />
        <Button variant="primary" type="submit">Buscar</Button>
      </form>
      {!q ? null : hits.isLoading ? (
        <Loading />
      ) : hits.error ? (
        <ErrorBox error={hits.error} />
      ) : !hits.data?.length ? (
        <Card><Empty>Sin resultados para “{q}”.</Empty></Card>
      ) : (
        <div className="space-y-2">
          <p className="text-sm">{hits.data.length} resultados</p>
          {hits.data.map((h) => (
            <Link key={`${h.entity_type}-${h.entity_id}-${h.page_id}`} to={hitLink(h)} className="block rounded-lg border border-gray-200 bg-white p-4 hover:border-gray-300 hover:bg-gray-50">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                {ICON[h.entity_type]} {KIND[h.entity_type]}
                {h.page_no ? ` · página ${h.page_no}` : ""}
              </div>
              <div className="mt-1 font-medium text-gray-900">{h.title}</div>
              <p className="mt-1 text-sm"><Snippet text={h.snippet} /></p>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
