import type { D1Database, R2Bucket } from "@cloudflare/workers-types";

export interface Env {
  DB: D1Database;
  FILES: R2Bucket;
  /** HMAC key for session JWTs. Rotating it logs everyone out. */
  SESSION_SECRET: string;
  /** torre3_ask: only copies of the ask_* views; the one database ask.ts runs model SQL on. */
  ASK_DB?: D1Database;
  /** Workers AI ("Preguntale al portal"). Missing in tests and when not configured. */
  AI?: { run: (model: string, input: unknown) => Promise<unknown> };
  /** Workers AI model for ask.ts; defaults to its DEFAULT_MODEL. */
  ASK_MODEL?: string;
}

export type CodeKind = "shared" | "unit" | "admin";

/** What the auth middleware hands to the API for each authenticated request. */
export interface SessionData {
  codeId: number;
  kind: CodeKind;
  deviceId: string;
}
