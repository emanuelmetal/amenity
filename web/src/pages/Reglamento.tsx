import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, NavLink, useParams } from "react-router";
import { PageViewer } from "../components/PageViewer";
import { Button, Card, Empty, ErrorBox, Input, Loading, PageHeader, StatusTag } from "../components/ui";
import { api, type Article, type ArticleIndex } from "../lib/api";

const norm = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

function ArticleView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["article", id], queryFn: () => api<Article>(`/reglamento/${id}`) });
  const [showScan, setShowScan] = useState(false);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const a = q.data!;
  const first = a.pages[0];
  return (
    <article className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm text-gray-500">{a.document_title ? `${a.document_title} · ` : ""}Artículo {a.numero}</div>
          <h2 className="text-lg font-semibold text-gray-900">{a.titulo || `Artículo ${a.numero}`}</h2>
        </div>
        <div className="flex items-center gap-2">
          {!a.verified && <StatusTag status="sin-verificar" />}
          {first && (
            <Button onClick={() => setShowScan((s) => !s)}>
              <FileText size={16} /> {showScan ? "Ocultar original" : "Ver original"}
            </Button>
          )}
        </div>
      </div>
      <div className="max-w-[70ch] whitespace-pre-line text-base leading-7 text-gray-700">{a.texto}</div>
      {showScan && (
        <div className="space-y-4">
          {a.pages.map((p) => (
            <div key={p.id}>
              <div className="mb-1 text-xs text-gray-500">Página {p.page_no}</div>
              <PageViewer pageId={p.id} documentId={p.document_id} pageNo={p.page_no} />
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

export default function Reglamento() {
  const { id } = useParams();
  const index = useQuery({ queryKey: ["reglamento"], queryFn: () => api<ArticleIndex[]>("/reglamento") });
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const f = norm(filter.trim());
    return (index.data ?? []).filter((a) => !f || norm(`${a.numero} ${a.titulo ?? ""}`).includes(f));
  }, [index.data, filter]);
  const groups = useMemo(() => {
    const m = new Map<string, ArticleIndex[]>();
    for (const a of shown) {
      const k = a.document_title ?? "Reglamento";
      m.set(k, [...(m.get(k) ?? []), a]);
    }
    return [...m.entries()];
  }, [shown]);

  return (
    <>
      <PageHeader
        title="Reglamentos"
        subtitle={
          <>
            Texto artículo por artículo. Para buscar dentro del texto completo usá <Link className="text-primary" to="/buscar">Buscar</Link>.
          </>
        }
      />
      {index.isLoading ? (
        <Loading />
      ) : index.error ? (
        <ErrorBox error={index.error} />
      ) : !index.data?.length ? (
        <Card><Empty>Los reglamentos todavía no fueron publicados.</Empty></Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
          <nav className="space-y-2 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
            <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrar artículos…" className="w-full" />
            {groups.map(([title, items]) => (
              <div key={title} className="space-y-1 pt-2">
                {groups.length > 1 && <div className="px-1 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</div>}
                <div className="space-y-0.5 border-l border-gray-200 pl-2">
                  {items.map((a) => (
                    <NavLink
                      key={a.id}
                      to={`/reglamento/${a.id}`}
                      className={({ isActive }) =>
                        `-ml-[9px] block border-l px-3 py-1.5 text-sm ${
                          isActive ? "border-primary font-semibold text-primary" : "border-transparent text-gray-700 hover:text-gray-900"
                        }`
                      }
                    >
                      <span className="tabular text-gray-400">Art. {a.numero}</span> {a.titulo}
                    </NavLink>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <Card>{id ? <ArticleView id={id} /> : <Empty>Elegí un artículo del índice.</Empty>}</Card>
        </div>
      )}
    </>
  );
}
