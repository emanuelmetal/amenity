export class ApiError extends Error {
  constructor(public status: number) {
    super(`HTTP ${status}`);
  }
}

type Param = string | number | undefined | null;

export async function api<T>(path: string, params?: Record<string, Param | Param[]>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, raw] of Object.entries(params ?? {}))
    for (const v of Array.isArray(raw) ? raw : [raw]) if (v !== undefined && v !== null && v !== "") qs.append(k, String(v));
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ""}`, { credentials: "same-origin" });
  if (res.status === 401) {
    // Session ended (code revoked or expired): reload to show the access page.
    window.location.reload();
  }
  if (!res.ok) throw new ApiError(res.status);
  return res.json() as Promise<T>;
}

/** Writes (comments). The browser adds the Origin header the server checks. */
export async function send<T>(method: "POST" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) window.location.reload();
  if (!res.ok) {
    const err = new ApiError(res.status);
    try {
      (err as ApiError & { code?: string }).code = ((await res.json()) as { error?: string }).error;
    } catch {
      /* not JSON */
    }
    throw err;
  }
  return res.json() as Promise<T>;
}

export interface Me {
  kind: "shared" | "unit" | "admin";
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
  fondo: number; // 1 = paid from the Fondo de obra: not part of the month's total
  tickets?: number; // linked receipts
  pagos?: number; // linked bank payments
  falta_comprobante?: number; // 1 = receipts were uploaded for its month but none is linked
  falta_pago?: number; // 1 = there is a bank statement for its month but no linked debit
}
export interface ExpensePage {
  rows: ExpenseRow[];
  count: number;
  total: number;
  fondo_total: number; // lines paid from the Fondo de obra, not in `total`
  page: number;
  pageSize: number;
}
/** An auditor's observation about the administration's accounts. */
export type ObservationState = "abierta" | "enviada" | "respondida" | "resuelta" | "descartada";
export interface Observation {
  id: string;
  period_id: string;
  tipo: string;
  titulo: string;
  detalle: string;
  importe: number | null;
  estado: ObservationState;
  fecha: string;
  respuesta: string | null;
  fecha_respuesta: string | null;
  lines: { id: number; period_id: string; rubro: string; concepto: string; detalle: string | null; importe: number }[];
  tickets: { id: number; fecha: string | null; proveedor: string | null; descripcion: string | null; total: number }[];
  movements: { id: number; fecha: string; descripcion: string; importe: number }[];
}

export interface ExpenseDetail extends Omit<ExpenseRow, "tickets" | "pagos"> {
  document_id: number | null;
  page_no: number | null;
  tickets: LinkedTicket[];
  payments: LinkedPayment[];
  actas: { acta_id: number; numero: number | null; fecha: string; id: number; tipo: ActaItemKind; texto: string; importe: number | null }[];
}

/** A debit of the consortium's bank statement linked to an expense line (proof of payment). */
export interface LinkedPayment {
  id: number;
  fecha: string;
  banco: string | null;
  descripcion: string;
  importe: number;
  // gastos = the statement's commissions and taxes, grouped; cheque = a cheque the
  // consortium issued that no statement shows cleared yet.
  kind: "debito" | "gastos" | "cheque";
  cheque_numero: string | null; // a cheque: on a debit, the one it cleared
  cheque_fecha_pago: string | null;
  items: { descripcion: string; importe: number; cantidad: number }[];
  score: number;
  status: "auto" | "verified";
  page_id: number | null;
  pages: { id: number; document_id: number; page_no: number }[];
}

export type TicketKind = "factura" | "recibo" | "presupuesto" | "ticket" | "servicio" | "nota_credito" | "nota_debito" | "otro";
export interface TicketRow {
  id: number;
  kind: TicketKind;
  letra: string | null;
  fecha: string | null;
  proveedor: string | null;
  descripcion: string | null;
  total: number;
  period_id: string | null;
  subcategoria: string | null;
  verified: number;
  source: "qr" | "llm" | "manual";
  page_id: number | null; // null when its page is private
  linked: number;
}
export interface TicketPage {
  rows: TicketRow[];
  count: number;
  total: number;
  page: number;
  pageSize: number;
}
export interface LinkedTicket extends Omit<TicketRow, "linked" | "period_id" | "subcategoria"> {
  score: number;
  status: "auto" | "verified";
}
export interface TicketDetail extends Omit<TicketRow, "page_id" | "linked"> {
  cuit: string | null;
  tipo_cmp: number | null;
  pto_vta: number | null;
  nro_cmp: number | null;
  cae: string | null;
  medio_pago: string | null;
  confidence: number;
  document_id: number;
  pages: { id: number; document_id: number; page_no: number }[];
  items: { descripcion: string; cantidad: number | null; importe: number | null }[];
  lines: { id: number; period_id: string; rubro: string; concepto: string; detalle: string | null; importe: number; score: number; status: string }[];
}
export interface MonthlyStat {
  id: string;
  gastos: number;
  ingresos: number | null;
  egresos: number | null;
  saldo_inicial: number | null;
  saldo_final: number | null;
  receipts: number;
  con_comprobante: number;
  lineas_sin_comprobante: number;
}
export interface RubroStat {
  period: string;
  rubro: string;
  total: number;
}
export interface VendorStat {
  proveedor: string;
  comprobantes: number;
  total: number;
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
  entity_type: "page" | "article" | "expense" | "ticket" | "acta";
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

export type ActaItemKind = "decision" | "tarea" | "tema";
export interface ActaSummary {
  id: number;
  numero: number | null;
  fecha: string;
  tipo: "comision" | "asamblea" | "otro";
  resumen: string;
  verified: number;
  items: { id: number; tipo: ActaItemKind; texto: string; importe: number | null }[];
}
export interface ActaDetail extends Omit<ActaSummary, "items"> {
  asistentes: string[];
  pages: { id: number; document_id: number; page_no: number }[];
  items: {
    id: number;
    orden: number;
    tipo: ActaItemKind;
    texto: string;
    importe: number | null;
    period_id: string | null;
    gastos: { id: number; period_id: string; rubro: string; concepto: string; detalle: string | null; importe: number }[];
    observaciones: { id: string; titulo: string; estado: ObservationState }[];
  }[];
}

export type CommentEntity = "general" | "expense" | "ticket" | "article" | "acta" | "observation";
export interface Comment {
  id: number;
  entity_type: CommentEntity;
  entity_id: number | string | null;
  body: string;
  created_at: string; // UTC, "YYYY-MM-DD HH:MM:SS"
  status: "visible" | "hidden";
  author: string;
  mine: boolean;
  reports?: number; // admins only
  moderated?: number;
  label?: string | null; // recent feed: what it is about
  history?: { action: "hide" | "restore"; moderator: number; at: string }[];
}
