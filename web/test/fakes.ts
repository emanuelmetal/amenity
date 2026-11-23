/** Minimal in-memory D1 and R2 stand-ins for unit tests (better-sqlite3 has FTS5). */
import Database from "better-sqlite3";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { Env } from "../server/env";

const MIGRATIONS = join(import.meta.dirname, "../../db/migrations");
const ASK_MIGRATIONS = join(import.meta.dirname, "../../db/ask_migrations");

class Stmt {
  private args: unknown[] = [];
  constructor(private db: Database.Database, private sql: string) {}
  bind(...args: unknown[]) {
    this.args = args;
    return this;
  }
  // D1 uses ?NNN placeholders; map them to named params better-sqlite3 understands.
  private s() {
    return this.db.prepare(this.sql.replace(/\?(\d+)/g, "@p$1"));
  }
  private get params() {
    return Object.fromEntries(this.args.map((v, i) => [`p${i + 1}`, v]));
  }
  async first<T>(): Promise<T | null> {
    const st = this.s();
    return ((st.reader ? st.get(this.params) : (st.run(this.params), undefined)) ?? null) as T | null;
  }
  async all<T>(): Promise<{ results: T[] }> {
    return { results: this.s().all(this.params) as T[] };
  }
  async run() {
    const st = this.s();
    if (st.reader) st.all(this.params);
    else st.run(this.params);
    return { success: true };
  }
}

export function fakeD1(dir = MIGRATIONS): { d1: Env["DB"]; raw: Database.Database } {
  const raw = new Database(":memory:");
  for (const f of readdirSync(dir).filter((f) => f.endsWith(".sql")).sort()) {
    raw.exec(readFileSync(join(dir, f), "utf8"));
  }
  const d1 = {
    prepare: (sql: string) => new Stmt(raw, sql),
    batch: async (stmts: Stmt[]) => Promise.all(stmts.map((s) => s.all())),
  };
  return { d1: d1 as unknown as Env["DB"], raw };
}

export function fakeR2(objects: Record<string, string>): Env["FILES"] {
  return {
    get: async (key: string) =>
      key in objects
        ? { body: new Response(objects[key]).body }
        : null,
  } as unknown as Env["FILES"];
}

/** The torre3_ask database, filled like pipeline/alas3/ask_sync.py does: every ask_* view of
 *  the main database (but ask_gastos_base) copied into the table of the same name. */
export function fakeAskD1(main: Database.Database): { d1: Env["DB"]; raw: Database.Database } {
  const ask = fakeD1(ASK_MIGRATIONS);
  syncAsk(main, ask.raw);
  return ask;
}

export function syncAsk(main: Database.Database, ask: Database.Database): void {
  const views = (main.prepare("SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'ask%' AND name != 'ask_gastos_base'").all() as { name: string }[]).map((r) => r.name);
  for (const v of views) {
    const cols = (ask.prepare(`SELECT name FROM pragma_table_info('${v}')`).all() as { name: string }[]).map((r) => r.name);
    if (!cols.length) throw new Error(`${v}: no table in the ask database`);
    ask.exec(`DELETE FROM ${v}`);
    const ins = ask.prepare(`INSERT INTO ${v} (${cols.join(", ")}) VALUES (${cols.map((c) => `@${c}`).join(", ")})`);
    for (const row of main.prepare(`SELECT * FROM ${v}`).all() as Record<string, unknown>[]) ins.run(row);
  }
}
