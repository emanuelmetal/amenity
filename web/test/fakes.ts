/** Minimal in-memory D1 and R2 stand-ins for unit tests (better-sqlite3 has FTS5). */
import Database from "better-sqlite3";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { Env } from "../server/env";

const MIGRATIONS = join(import.meta.dirname, "../../db/migrations");

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

export function fakeD1(): { d1: Env["DB"]; raw: Database.Database } {
  const raw = new Database(":memory:");
  for (const f of readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort()) {
    raw.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
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
