import { FileText, ZoomIn, ZoomOut } from "lucide-react";
import { useState } from "react";
import { documentPdfUrl, pageImageUrl } from "../lib/api";
import { Button, buttonClass } from "./ui";

/** Zoomable scan of one page, plus a link to the original PDF at that page. */
export function PageViewer({ pageId, documentId, pageNo, compact }: { pageId: number; documentId: number; pageNo: number; compact?: boolean }) {
  const [zoom, setZoom] = useState(1);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button variant="ghost" onClick={() => setZoom((z) => Math.max(1, z - 0.5))} aria-label="Alejar" disabled={zoom <= 1}>
            <ZoomOut size={16} />
          </Button>
          <span className="tabular w-10 text-center text-xs">{Math.round(zoom * 100)}%</span>
          <Button variant="ghost" onClick={() => setZoom((z) => Math.min(4, z + 0.5))} aria-label="Acercar" disabled={zoom >= 4}>
            <ZoomIn size={16} />
          </Button>
        </div>
        <a className={buttonClass()} href={documentPdfUrl(documentId, pageNo)} target="_blank" rel="noreferrer noopener">
          <FileText size={16} /> Ver PDF original
        </a>
      </div>
      <div className={`overflow-auto rounded-lg border border-gray-200 bg-gray-100 ${compact ? "max-h-[60vh]" : "max-h-[80vh]"}`}>
        <img
          src={pageImageUrl(pageId)}
          alt={`Página ${pageNo} del documento original`}
          style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
          className="block bg-white"
          loading="lazy"
        />
      </div>
    </div>
  );
}
