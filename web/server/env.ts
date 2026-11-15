import type { D1Database, R2Bucket } from "@cloudflare/workers-types";

export interface Env {
  DB: D1Database;
  FILES: R2Bucket;
  /** HMAC key for session JWTs. Rotating it logs everyone out. */
  SESSION_SECRET: string;
}

export type CodeKind = "shared" | "unit" | "admin";

/** What the auth middleware hands to the API for each authenticated request. */
export interface SessionData {
  codeId: number;
  kind: CodeKind;
  deviceId: string;
}
