export class ApiError extends Error {
  constructor(public status: number) {
    super(`HTTP ${status}`);
  }
}

export async function api<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ""}`, { credentials: "same-origin" });
  if (res.status === 401) {
    // Session ended (code revoked or expired): reload to show the access page.
    window.location.reload();
  }
  if (!res.ok) throw new ApiError(res.status);
  return res.json() as Promise<T>;
}

export const pageImageUrl = (pageId: number) => `/api/files/page/${pageId}`;
export const documentPdfUrl = (documentId: number, pageNo?: number) =>
  `/api/files/doc/${documentId}${pageNo ? `#page=${pageNo}` : ""}`;

export interface Period {
  id: string;
  total: number | null;
  document_id: number | null;
  lines_total: number;
  lines: number;
}
export interface Rubro {
  rubro: string;
  lines: number;
  total: number;
}
export interface ExpenseRow {
  id: number;
  period_id: string;
  rubro: string;
  subcategoria: string | null;
  concepto: string;
  detalle: string | null;
  proveedor: string | null;
  importe: number;
  page_id: number | null;
  confidence: number;
  verified: number;
}
export interface ExpensePage {
  rows: ExpenseRow[];
  count: number;
  total: number;
  page: number;
  pageSize: number;
}
export interface ExpenseDetail extends ExpenseRow {
  document_id: number | null;
  page_no: number | null;
}
export interface ArticleIndex {
  id: number;
  numero: string;
  titulo: string | null;
  verified: number;
  document_id: number | null;
  document_title: string | null;
}
export interface Article extends ArticleIndex {
  texto: string;
  pages: { id: number; document_id: number; page_no: number }[];
}
export interface SearchHit {
  entity_type: "page" | "article" | "expense" | "acta_item";
  entity_id: number;
  page_id: number | null;
  title: string;
  snippet: string;
  document_id: number | null;
  page_no: number | null;
}
export interface PageInfo {
  id: number;
  document_id: number;
  page_no: number;
  text: string;
  ocr_engine: string;
  document_title: string;
  document_kind: string;
  period: string | null;
  document_pages: number;
  prev_id: number | null;
  next_id: number | null;
}
