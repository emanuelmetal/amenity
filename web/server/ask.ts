/**
 * "Preguntale al portal" (PLAN.md §6.9, Phase 4). SECURITY CRITICAL.
 *
 * A neighbour's question goes to an LLM (Workers AI) together with the description of the
 * ask_* views (db/migrations/0009_ask.sql). The model answers with ONE SELECT. Before it
 * runs, `guardSql` checks it token by token, deny by default:
 *   - a single SELECT: no comments, no ';' inside, no quoted identifiers, no parameters, no WITH;
 *   - every word is an allowed keyword, an allowed function (only before '('), one of the
 *     ask_* views below, one of their columns, or an alias the query itself declares;
 *   - every table position (after FROM, JOIN, a comma of a FROM list, or IN) is an ask_* view
 *     or a subquery, so no other table, sqlite_* schema table or table-valued function is reachable.
 * The checked query runs wrapped as `SELECT * FROM (<sql>) LIMIT n`, which SQLite only accepts
 * for a query, and ONLY on ASK_DB (D1 `torre3_ask`), which holds nothing but copies of the
 * ask_* views made at publish (pipeline/alas3/ask_sync.py): even a gap in the guard cannot
 * reach comments or access codes, and a slow query cannot stall the main database. Without
 * ASK_DB the feature is off (never falls back to DB). The model never sees any data (only the question and the schema), so a
 * question cannot make it leak rows; everything it can read is already on the site.
 * Questions are not stored. Rate limits: per device (shared link) or per access code
 * (unit/admin links) per day, plus a global daily cap for the Workers AI free allocation.
 */
import { Hono } from "hono";
import type { Context } from "hono";
import { keyedHash } from "./comments";
import type { Env, SessionData } from "./env";

type Bindings = Env & { session: SessionData };
type C = Context<{ Bindings: Bindings }>;

export const MAX_QUESTION = 300;
export const MAX_SQL = 2500;
export const MAX_ROWS = 200;
/** Relations one query may name (bounds cross joins: D1 runs one query at a time). */
export const MAX_TABLES = 3;
export const DAILY_PER_USER = 20;
export const DAILY_GLOBAL = 300;
const DEFAULT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast";

/** The only relations generated SQL may read, with what the model is told about them. */
export const VIEWS: Record<string, { desc: string; cols: Record<string, string> }> = {
  ask_meses: {
    desc: "Una fila por mes liquidado (liquidación de expensas).",
    cols: {
      mes: "texto 'YYYY-MM'", anio: "entero", total_gastos: "total de gastos ordinarios del mes",
      ingresos: "cobranzas del mes", egresos: "pagos del mes", saldo_inicial: "saldo al inicio", saldo_final: "saldo al cierre",
    },
  },
  ask_gastos: {
    desc: "Una fila por línea de gasto de la liquidación mensual.",
    cols: {
      id: "id", mes: "texto 'YYYY-MM' de la liquidación", anio: "entero", rubro: "rubro de la administración",
      subcategoria: "categoría (p. ej. 'movilidad/taxi', 'limpieza', 'ascensor', 'encargado')", concepto: "concepto",
      detalle: "detalle", proveedor: "proveedor (puede ser NULL)", importe: "importe en pesos",
      fondo_reserva: "1 = salida del fondo de obra/reserva (no suma al total del mes), 0 = gasto ordinario",
      verificado: "1 = revisado a mano", con_comprobante: "1 = tiene comprobante vinculado", con_pago: "1 = tiene pago bancario vinculado",
      hay_comprobantes_del_mes: "1 = se recibieron comprobantes para ese mes", hay_resumen_bancario_del_mes: "1 = hay resumen bancario de ese mes",
      respaldado: "1 = tiene el comprobante y el pago que se pueden exigir según la documentación recibida",
    },
  },
  ask_comprobantes: {
    desc: "Una fila por comprobante (factura, ticket, recibo, presupuesto) entregado por la administración.",
    cols: {
      id: "id", mes: "texto 'YYYY-MM'", fecha: "texto 'YYYY-MM-DD' (puede ser NULL)",
      tipo: "'factura', 'ticket', 'recibo', 'presupuesto', etc.", letra: "letra de factura (A, B, C)",
      proveedor: "emisor", descripcion: "qué se compró", total: "importe en pesos", subcategoria: "categoría",
      verificado: "1 = revisado a mano", etiquetas: "etiquetas separadas por coma (p. ej. 'movilidad/taxi')",
    },
  },
  ask_gasto_comprobante: {
    desc: "Vínculos entre gastos y comprobantes.",
    cols: { gasto_id: "ask_gastos.id", comprobante_id: "ask_comprobantes.id", estado: "'confirmado', 'automatico' o 'posible'" },
  },
  ask_movimientos: {
    desc: "Débitos de la cuenta bancaria del consorcio (los créditos no se publican).",
    cols: {
      id: "id", mes: "texto 'YYYY-MM'", fecha: "texto 'YYYY-MM-DD'", banco: "banco", descripcion: "descripción del banco",
      importe: "importe en pesos (positivo = salió de la cuenta)",
      tipo: "'debito', 'gastos' (comisiones e impuestos agrupados) o 'cheque' (cheque emitido aún no debitado)", cheque_numero: "número de cheque",
    },
  },
  ask_gasto_pago: {
    desc: "Vínculos entre gastos y movimientos bancarios que los pagaron.",
    cols: { gasto_id: "ask_gastos.id", movimiento_id: "ask_movimientos.id", estado: "'confirmado', 'automatico' o 'posible'" },
  },
  ask_observaciones: {
    desc: "Observaciones del control de las cuentas, para la administración.",
    cols: {
      id: "id texto", mes: "texto 'YYYY-MM'", tipo: "tipo de hallazgo", titulo: "título", detalle: "detalle", importe: "importe en juego",
      estado: "'abierta', 'enviada', 'respondida' o 'resuelta'", fecha: "fecha", respuesta: "respuesta", fecha_respuesta: "fecha de la respuesta",
    },
  },
  ask_actas: {
    desc: "Actas de reuniones de la comisión y de asambleas.",
    cols: { id: "id", numero: "número de acta", fecha: "texto 'YYYY-MM-DD'", tipo: "'comision', 'asamblea' u 'otro'", resumen: "resumen", verificada: "1 = revisada" },
  },
  ask_acta_items: {
    desc: "Decisiones, tareas y temas de cada acta.",
    cols: { id: "id", acta_id: "ask_actas.id", orden: "orden", tipo: "'decision', 'tarea' o 'tema'", texto: "texto", importe: "importe mencionado", mes: "mes al que se refiere" },
  },
  ask_articulos: {
    desc: "Artículos del reglamento de copropiedad.",
    cols: { id: "id", numero: "número", orden: "orden", titulo: "título", texto: "texto completo" },
  },
};

const VIEW_NAMES = new Set(Object.keys(VIEWS));
const COLUMNS = new Set(Object.values(VIEWS).flatMap((v) => Object.keys(v.cols)));
// No WITH/RECURSIVE (unbounded recursion), no window functions, no MATCH/REGEXP.
const KEYWORDS = new Set(
  ("select distinct all from where group by having order asc desc limit offset as and or not in is null " +
    "like glob between case when then else end join left inner cross outer on using exists union except " +
    "intersect cast integer real text numeric collate nocase escape true false nulls first last").split(" "),
);
// Only before '('. No replace/printf/format/zeroblob/randomblob (memory), no json_*, no sqlite_*, no load_extension.
const FUNCTIONS = new Set(
  ("count sum total avg min max round abs coalesce ifnull nullif iif lower upper substr substring length " +
    "trim ltrim rtrim instr strftime date julianday group_concat").split(" "),
);
const ENDS_FROM = new Set(["where", "group", "order", "having", "limit", "union", "except", "intersect"]);
const PUNCT = ["<=", ">=", "!=", "<>", "==", "||", "(", ")", ",", ".", "*", "+", "-", "/", "%", "=", "<", ">"];

type Tok = { t: "word" | "str" | "num" | "p"; v: string };

export class SqlRejected extends Error {}

function tokenize(sql: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < sql.length) {
    const ch = sql[i];
    if (" \t\n\r\f".includes(ch)) { i++; continue; }
    if (sql.startsWith("--", i) || sql.startsWith("/*", i)) throw new SqlRejected("no se permiten comentarios");
    if (ch === "'") {
      let j = i + 1;
      let v = "";
      for (;;) {
        if (j >= sql.length) throw new SqlRejected("texto sin cerrar");
        if (sql[j] === "'") {
          if (sql[j + 1] === "'") { v += "'"; j += 2; continue; }
          break;
        }
        v += sql[j++];
      }
      if (v.length > 200) throw new SqlRejected("texto demasiado largo");
      out.push({ t: "str", v });
      i = j + 1;
      continue;
    }
    const num = /^\d+(\.\d+)?/.exec(sql.slice(i));
    if (num) { out.push({ t: "num", v: num[0] }); i += num[0].length; continue; }
    const word = /^[A-Za-z_][A-Za-z0-9_]*/.exec(sql.slice(i));
    if (word) {
      // x'..' blob literals and words glued to a string or digit run.
      if (sql[i + word[0].length] === "'") throw new SqlRejected("literal no permitido");
      out.push({ t: "word", v: word[0].toLowerCase() });
      i += word[0].length;
      continue;
    }
    const p = PUNCT.find((s) => sql.startsWith(s, i));
    if (p) { out.push({ t: "p", v: p }); i += p.length; continue; }
        throw new SqlRejected(`carácter no permitido: ${JSON.stringify(ch)}`);
  }
  return out;
}

const isWord = (t: Tok | undefined, ...vs: string[]) => t?.t === "word" && (vs.length === 0 || vs.includes(t.v));
const isP = (t: Tok | undefined, v: string) => t?.t === "p" && t.v === v;

/** Names an alias may never take (defence in depth: table positions only accept views anyway). */
const DENY_ALIAS = /^(sqlite_|pragma_|ask_|search_fts|d1_|_cf_|idx_)|^(access_codes|access_attempts|comments|comment_reports|comment_moderation|documents|pages|periods|expense_lines|tickets|ticket_items|expense_ticket_links|tags|entity_tags|reglamento_articles|actas|acta_items|acta_expense_links|bank_movements|bank_movements_new|expense_payment_links|observations|search_fts|main|temp)$/;

function declareAlias(tok: Tok | undefined, aliases: Set<string>): void {
  if (tok?.t !== "word" || KEYWORDS.has(tok.v) || DENY_ALIAS.test(tok.v)) {
    throw new SqlRejected(`alias no permitido: ${tok?.v ?? ""}`);
  }
  aliases.add(tok.v);
}

/**
 * Returns the query (without a trailing ';') if it only reads the ask_* views; throws
 * SqlRejected otherwise. Table positions are only after FROM and JOIN (comma joins and
 * parenthesised tables/joins are refused): each must be an ask_* view or `(SELECT …)`,
 * optionally followed by an alias, and a JOIN must continue with ON or USING. Aliases are
 * declared only there or right after AS.
 */
export function guardSql(sql: string): string {
  const q = sql.trim().replace(/;$/, "").trim();
  if (!q) throw new SqlRejected("consulta vacía");
  if (q.length > MAX_SQL) throw new SqlRejected("consulta demasiado larga");
  const toks = tokenize(q);
  if (!isWord(toks[0], "select")) throw new SqlRejected("solo se permite SELECT");

  // Matching parentheses.
  const close = new Map<number, number>();
  const open: number[] = [];
  toks.forEach((t, i) => {
    if (isP(t, "(")) open.push(i);
    else if (isP(t, ")")) {
      const o = open.pop();
      if (o === undefined) throw new SqlRejected("paréntesis desbalanceados");
      close.set(o, i);
    }
  });
  if (open.length) throw new SqlRejected("paréntesis desbalanceados");

  // Table positions and aliases.
  const aliases = new Set<string>();
  const declared = new Set<number>(); // token indexes that declare an alias
  let tables = 0;
  toks.forEach((t, i) => {
    if (isWord(t, "as") && toks[i + 1]?.t === "word" && !KEYWORDS.has(toks[i + 1].v)) {
      declareAlias(toks[i + 1], aliases);
      declared.add(i + 1);
    }
    if (!isWord(t, "from", "join")) return;
    if (++tables > MAX_TABLES) throw new SqlRejected(`como máximo ${MAX_TABLES} vistas o subconsultas por consulta`);
    const first = toks[i + 1];
    let j: number;
    if (first?.t === "word" && VIEW_NAMES.has(first.v)) j = i + 2;
    else if (isP(first, "(") && isWord(toks[i + 2], "select")) j = close.get(i + 1)! + 1;
    else throw new SqlRejected(`solo se pueden consultar las vistas ask_* o una subconsulta: ${first?.v ?? "nada"}`);
    if (isWord(toks[j], "as")) j += 2; // declared above
    else if (toks[j]?.t === "word" && !KEYWORDS.has(toks[j].v)) {
      declareAlias(toks[j], aliases);
      declared.add(j);
      j++;
    }
    if (isP(toks[j], ",")) throw new SqlRejected("usá JOIN … ON en lugar de comas entre vistas");
    if (isWord(t, "join") && !isWord(toks[j], "on", "using")) throw new SqlRejected("cada JOIN necesita ON o USING");
  });

  const frames: { inFrom: boolean }[] = [{ inFrom: false }];
  for (let i = 0; i < toks.length; i++) {
    const tok = toks[i];
    const frame = frames[frames.length - 1];
    if (tok.t === "p") {
      if (tok.v === "(") frames.push({ inFrom: false });
      else if (tok.v === ")") frames.pop();
      else if (tok.v === "," && frame.inFrom) throw new SqlRejected("usá JOIN … ON en lugar de comas entre vistas");
      continue;
    }
    if (tok.t !== "word" || declared.has(i)) continue;
    const w = tok.v;
    if (w === "from") frame.inFrom = true;
    if (ENDS_FROM.has(w)) frame.inFrom = false;
    if (w === "in" && !isP(toks[i + 1], "(")) throw new SqlRejected("IN necesita una lista o subconsulta entre paréntesis");
    if (w === "select" && i > 0 && !isP(toks[i - 1], "(") && !isWord(toks[i - 1], "union", "except", "intersect", "all")) {
      throw new SqlRejected("SELECT fuera de lugar");
    }
    if (isP(toks[i + 1], "(")) {
      if (FUNCTIONS.has(w) || ["in", "exists", "cast", "as", "on", "using", "from", "join", "and", "or", "not", "then", "else", "when", "case", "by", "select", "where", "having", "union", "all", "distinct"].includes(w)) continue;
      throw new SqlRejected(`función no permitida: ${w}`);
    }
    if (isP(toks[i - 1], ".")) {
      if ((COLUMNS.has(w) || aliases.has(w)) && toks[i - 2]?.t === "word") continue;
      throw new SqlRejected(`columna desconocida: ${w}`);
    }
    if (isP(toks[i + 1], ".") && !(VIEW_NAMES.has(w) || aliases.has(w))) throw new SqlRejected(`nombre desconocido: ${w}`);
    if (KEYWORDS.has(w) || VIEW_NAMES.has(w) || COLUMNS.has(w) || aliases.has(w)) continue;
    throw new SqlRejected(`nombre desconocido: ${w}`);
  }
  return q;
}

export function schemaPrompt(): string {
  return Object.entries(VIEWS)
    .map(([name, v]) => `${name}: ${v.desc}\n${Object.entries(v.cols).map(([c, d]) => `  - ${c}: ${d}`).join("\n")}`)
    .join("\n\n");
}

const SYSTEM = `Sos un asistente que traduce preguntas de vecinos de un edificio (Torre 3, Córdoba, Argentina) sobre las expensas y la administración a UNA consulta SQLite de solo lectura.

Solo podés usar estas vistas y columnas:

${schemaPrompt()}

Reglas:
- Respondé SOLO un objeto JSON, sin texto alrededor: {"titulo": "<título corto de la respuesta, en español>", "sql": "<una consulta SELECT>"}.
- Si la pregunta no se puede responder con estas vistas, respondé {"titulo": "", "sql": "", "motivo": "<explicación breve en español>"}.
- Una sola sentencia SELECT. Sin comentarios, sin WITH, sin punto y coma, sin comillas dobles. Textos entre comillas simples.
- Los meses son textos 'YYYY-MM' (columna mes). "Este año" o "en 2026": anio = 2026. El ejercicio va de septiembre a agosto.
- Para buscar texto usá lower(columna) LIKE '%palabra%' sobre concepto, detalle, proveedor o descripcion; probá con la raíz de la palabra (p. ej. '%ascensor%').
- Los totales de gastos del mes excluyen fondo_reserva = 1 salvo que la pregunta hable del fondo de reserva.
- Usá alias con AS para cada columna calculada (p. ej. SUM(importe) AS total). Nombres de columnas en español.
- Para combinar vistas usá JOIN … ON (nunca comas entre vistas); como máximo 3 vistas o subconsultas en total.
- Ordená el resultado de forma útil y limitá a 100 filas si puede haber muchas.`;

const EXAMPLES: { q: string; a: { titulo: string; sql: string } }[] = [
  {
    q: "¿Cuánto se gastó en taxis del encargado por mes?",
    a: {
      titulo: "Taxis del encargado por mes",
      sql: "SELECT mes, COUNT(*) AS viajes, SUM(total) AS total FROM ask_comprobantes WHERE etiquetas LIKE '%movilidad/taxi%' GROUP BY mes ORDER BY mes",
    },
  },
  {
    q: "¿Qué gastos de 2026 no tienen respaldo?",
    a: {
      titulo: "Gastos de 2026 sin respaldo completo",
      sql: "SELECT mes, rubro, concepto, detalle, importe, con_comprobante, con_pago FROM ask_gastos WHERE anio = 2026 AND respaldado = 0 AND (hay_comprobantes_del_mes = 1 OR hay_resumen_bancario_del_mes = 1) ORDER BY importe DESC LIMIT 100",
    },
  },
];

export interface AskResult {
  titulo: string;
  sql: string;
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
}

type Ai = { run: (model: string, input: unknown) => Promise<unknown> };

/** Pulls {"titulo","sql","motivo"} out of a model reply (JSON, maybe fenced or with prose). */
export function parseReply(reply: unknown): { titulo: string; sql: string; motivo?: string } {
  const r = reply as { response?: unknown } | null;
  let body: unknown = r && typeof r === "object" && "response" in r ? r.response : reply;
  if (typeof body === "string") {
    const m = /\{[\s\S]*\}/.exec(body);
    if (!m) {
      const sql = /```(?:sql)?\s*([\s\S]*?)```/i.exec(body)?.[1] ?? body;
      return { titulo: "", sql: sql.trim() };
    }
    try {
      body = JSON.parse(m[0]);
    } catch {
      throw new SqlRejected("respuesta del modelo ilegible");
    }
  }
  const o = (body ?? {}) as Record<string, unknown>;
  const s = (v: unknown) => (typeof v === "string" ? v : "");
  return { titulo: s(o.titulo).slice(0, 200), sql: s(o.sql), motivo: s(o.motivo).slice(0, 500) || undefined };
}

export class CannotAnswer extends Error {}

export const MAX_CELL = 1000;
/** Bounds what one cell can add to the response (group_concat and || can build long strings). */
function clip(v: unknown): unknown {
  return typeof v === "string" && v.length > MAX_CELL ? `${v.slice(0, MAX_CELL)}…` : v;
}

/** Question -> checked SQL -> rows. One retry, telling the model why its first query failed. */
export async function answer(ai: Ai, db: Env["DB"], model: string, question: string): Promise<AskResult> {
  const messages: { role: string; content: string }[] = [{ role: "system", content: SYSTEM }];
  for (const ex of EXAMPLES) {
    messages.push({ role: "user", content: ex.q }, { role: "assistant", content: JSON.stringify(ex.a) });
  }
  messages.push({ role: "user", content: question });
  let lastError = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    const reply = await ai.run(model, { messages: [...messages], max_tokens: 700, temperature: 0 });
    const parsed = parseReply(reply);
    if (!parsed.sql.trim()) throw new CannotAnswer(parsed.motivo || "No encontré cómo responder esa pregunta con los datos del portal.");
    try {
      const sql = guardSql(parsed.sql);
      const { results } = await db.prepare(`SELECT * FROM (${sql}) LIMIT ${MAX_ROWS + 1}`).all<Record<string, unknown>>();
      const columns = results.length ? Object.keys(results[0]) : [];
      return {
        titulo: parsed.titulo || "Resultado",
        sql,
        columns,
        rows: results.slice(0, MAX_ROWS).map((r) => columns.map((c) => clip(r[c]))),
        truncated: results.length > MAX_ROWS,
      };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      // Only mistakes the model can fix are retried; anything else (time or memory limits,
      // whatever D1 calls them) already cost a lot and is not run again.
      if (!(e instanceof SqlRejected) && !/no such column|ambiguous column|syntax error|no such function|misuse|mismatch|incomplete input/i.test(msg)) {
        throw new CannotAnswer("La consulta tardó demasiado. Probá con una pregunta más acotada.");
      }
      lastError = e instanceof SqlRejected ? e.message : `error al ejecutar: ${msg}`.slice(0, 300);
      messages.push(
        { role: "assistant", content: JSON.stringify({ titulo: parsed.titulo, sql: parsed.sql }) },
        { role: "user", content: `Esa consulta no sirve (${lastError}). Corregila respetando las reglas y respondé solo el JSON.` },
      );
    }
  }
  throw new CannotAnswer("No pude armar una consulta válida para esa pregunta. Probá reformularla.");
}

export const ask = new Hono<{ Bindings: Bindings }>();

/** CSRF: same rule as comments (Origin = the site, JSON body). */
ask.use("*", async (c, next) => {
  if (c.req.method !== "GET" && c.req.method !== "HEAD") {
    const origin = c.req.header("Origin");
    if (!origin || origin !== new URL(c.req.url).origin) return c.json({ error: "bad_origin" }, 403);
    if (!(c.req.header("Content-Type") ?? "").startsWith("application/json")) return c.json({ error: "bad_content_type" }, 415);
  }
  await next();
  c.res.headers.set("Cache-Control", "no-store");
});

const today = () => new Date().toISOString().slice(0, 10);

/** Counts one question against `key`'s daily limit; false when the limit is reached. */
async function take(db: Env["DB"], key: string, limit: number): Promise<boolean> {
  const row = await db
    .prepare(
      `INSERT INTO ask_usage (day, key, n) VALUES (?1, ?2, 1)
       ON CONFLICT (day, key) DO UPDATE SET n = n + 1 WHERE n < ?3
       RETURNING n`,
    )
    .bind(today(), key, limit)
    .first<{ n: number }>();
  return row !== null;
}

async function userKey(c: C): Promise<string> {
  const s = c.env.session;
  return keyedHash(c.env.SESSION_SECRET, "ask-v1", s.kind === "shared" ? `device:${s.deviceId}` : `code:${s.codeId}`);
}

/** Objects allowed in ASK_DB besides the ask_* copies: D1's migration log and SQLite/D1 internals. */
const ASK_DB_INTERNAL = /^(d1_migrations|sqlite_.*|_cf_.*)$/;
const isolationChecked = new WeakMap<object, Promise<boolean>>();

/** True only when ASK_DB holds nothing but the ask_* tables (and their indexes). Guards against
 *  a wrangler.toml that points ASK_DB at the main database: then the feature is off. Cached per
 *  binding object (one query per isolate). */
export function askDbIsolated(askDb: NonNullable<Env["ASK_DB"]>): Promise<boolean> {
  let p = isolationChecked.get(askDb);
  if (!p) {
    p = askDb
      .prepare("SELECT tbl_name FROM sqlite_master")
      .all<{ tbl_name: string }>()
      .then(({ results }) => results.every((r) => r.tbl_name in VIEWS || ASK_DB_INTERNAL.test(r.tbl_name)))
      .catch(() => false);
    p.then((ok) => {
      if (!ok) {
        isolationChecked.delete(askDb); // re-check next time (a transient error must not stick)
        console.error("ask: ASK_DB is not the isolated torre3_ask database; feature off");
      }
    });
    isolationChecked.set(askDb, p);
  }
  return p;
}

async function usable(env: Env): Promise<boolean> {
  return Boolean(env.AI && env.ASK_DB && (await askDbIsolated(env.ASK_DB)));
}

ask.get("/", async (c) => {
  const row = await c.env.DB.prepare("SELECT n FROM ask_usage WHERE day = ?1 AND key = ?2")
    .bind(today(), await userKey(c))
    .first<{ n: number }>();
  return c.json({ available: await usable(c.env), limit: DAILY_PER_USER, remaining: Math.max(0, DAILY_PER_USER - (row?.n ?? 0)) });
});

ask.post("/", async (c) => {
  const ai = c.env.AI;
  const askDb = c.env.ASK_DB;
  if (!ai || !askDb || !(await usable(c.env))) return c.json({ error: "unavailable" }, 503);
  let question: unknown;
  try {
    question = ((await c.req.json()) as { pregunta?: unknown }).pregunta;
  } catch {
    return c.json({ error: "bad_request" }, 400);
  }
  if (typeof question !== "string" || !question.trim()) return c.json({ error: "bad_request" }, 400);
  if (question.length > MAX_QUESTION) return c.json({ error: "too_long", max: MAX_QUESTION }, 400);
  const key = await userKey(c);
  if (!(await take(c.env.DB, key, DAILY_PER_USER))) return c.json({ error: "rate_limited", limit: DAILY_PER_USER }, 429);
  if (!(await take(c.env.DB, "*", DAILY_GLOBAL))) {
    // Not the user's fault: give their question back.
    await c.env.DB.prepare("UPDATE ask_usage SET n = n - 1 WHERE day = ?1 AND key = ?2 AND n > 0").bind(today(), key).run();
    return c.json({ error: "global_limit" }, 429);
  }
  try {
    return c.json(await answer(ai, askDb, c.env.ASK_MODEL || DEFAULT_MODEL, question.trim()));
  } catch (e) {
    if (e instanceof CannotAnswer) return c.json({ error: "cannot_answer", mensaje: e.message }, 422);
    // Never log the question or the model's text (it may echo the question).
    console.error("ask failed", e instanceof Error ? e.name : typeof e);
    return c.json({ error: "failed" }, 502);
  }
});
