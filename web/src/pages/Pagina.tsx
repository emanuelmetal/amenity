import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { PageViewer } from "../components/PageViewer";
import { buttonClass, Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { api, type PageInfo } from "../lib/api";
import { formatPeriod } from "../lib/format";

export default function Pagina() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["page", id], queryFn: () => api<PageInfo>(`/pages/${id}`) });
  const [showText, setShowText] = useState(false);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const p = q.data!;
  return (
    <>
      <PageHeader
        title={p.document_title}
        subtitle={`Página ${p.page_no} de ${p.document_pages}${p.period ? ` · ${formatPeriod(p.period)}` : ""}`}
        actions={
          <>
            {p.prev_id && <Link className={buttonClass()} to={`/paginas/${p.prev_id}`}><ChevronLeft size={16} /> Anterior</Link>}
            {p.next_id && <Link className={buttonClass()} to={`/paginas/${p.next_id}`}>Siguiente <ChevronRight size={16} /></Link>}
          </>
        }
      />
      <Card>
        <PageViewer pageId={p.id} documentId={p.document_id} pageNo={p.page_no} />
      </Card>
      <Card title="Texto reconocido" actions={<button className="text-sm text-primary" onClick={() => setShowText((s) => !s)}>{showText ? "Ocultar" : "Mostrar"}</button>}>
        {showText ? (
          <pre className="whitespace-pre-wrap font-sans text-sm">{p.text || "Sin texto."}</pre>
        ) : (
          <p className="text-sm text-gray-400">
            Texto extraído {p.ocr_engine === "tesseract" ? "por OCR (puede tener errores)" : "del PDF"}. Los datos personales están ocultos.
          </p>
        )}
      </Card>
    </>
  );
}
