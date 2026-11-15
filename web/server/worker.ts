/**
 * Worker entry. `run_worker_first = true` in wrangler.toml, so every request,
 * static assets included, passes through the access gate first.
 */
import type { ExecutionContext, Fetcher } from "@cloudflare/workers-types";
import { api } from "./api";
import { gate } from "./auth";
import type { Env } from "./env";

type WorkerEnv = Env & { ASSETS: Fetcher };

export default {
  async fetch(request: Request, env: WorkerEnv, ctx: ExecutionContext): Promise<Response> {
    return gate(request, env, async (session) => {
      const { pathname } = new URL(request.url);
      if (pathname.startsWith("/api/")) {
        return api.fetch(request, { ...env, session }, ctx);
      }
      return env.ASSETS.fetch(request as never) as unknown as Response;
    });
  },
};
