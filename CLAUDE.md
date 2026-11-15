# Torre 3 portal (Alas 3) — Claude Code notes

Private, read-mostly transparency portal for the 64 units of Torre 3. Full spec: `PLAN.md`. Visual spec: `design/DESIGN.md` + `design/theme.css`.

## Hard rules
- **Never commit anything under `data/`** (personal data: scans, OCR text, extracted rows). It is git-ignored; keep it that way.
- UI text in **Spanish (es-AR)**; code, comments, docs in English.
- Money: `Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS'})`. Dates: `14 nov 2026`.
- R2 is never public. Every file goes through `/api/files/*` after the cookie check.
- Privacy is fail-closed (`pipeline/alas3/redact.py`, `ingest.py`): payroll pages, debt listings and unreadable scans are `restricted` (never served or indexed); the "Unidades en mora" block of a liquidación is blacked out; person CUIL/DNI/CBU are masked in every published string AND blacked out in the PDF/images. Only `data/work/docs/*/public.pdf` and renders made from it are ever uploaded.
- Manual review overrides: `data/work/restrict.json` → `{"<sha16>": {"restrict": [pages], "allow": [pages]}}`, then `make ingest ARGS=--force` and publish.
- Only `config.PHASE_KINDS` are ingested/published (Phase 1: reglamento, liquidacion).
- Data with `verified = 0` shows a "Sin verificar" tag.

## Layout
```
pipeline/      Python 3.12 (uv). alas3/{ingest,ocr,extract,classify,validate,redact,publish,links}.py
web/           Vite + React + TS SPA served by one Cloudflare Worker with static assets
  server/worker.ts              entry; run_worker_first=true so the gate covers assets too
  server/auth.ts                access-link auth (security critical)
  server/api.ts                 Hono read API
db/migrations/ D1 SQL migrations; db/seed.dev.sql = FAKE data for local dev only
data/          git-ignored: inbox/ (admin PDFs; kind subfolders or classified by file name), work/ (cache), out/
```

## Commands (Makefile)
- `make setup` — install Python + Node deps
- `make migrate-local` / `make migrate` — apply D1 migrations (local Miniflare / remote)
- `make seed-local` — load fake dev data
- `make ingest` → `make validate` → `make publish-local` | `make publish`
- `make dev` — build SPA and run `wrangler dev` on :8788 with local D1/R2
- `make new-link [LOCAL=1] [UNIT=UF12]`, `make rotate-link`, `make admin-link`
- `make test` — pytest + ruff + vitest + tsc
- `make backup` — D1 export of base tables (FTS excluded; restore = migrations + dump + db/rebuild_fts.sql)

## Access model
`/acceso?k=<token>` → `sha256(token)` looked up in `access_codes` (active, unexpired) → HS256 JWT cookie `t3s` (180 days, HttpOnly, Secure, SameSite=Lax) → 302 `/`. Each request re-checks the JWT **and** that the code is still active (revocation works immediately). `/acceso` allows 10 FAILED attempts/h per hashed IP (successes never count: CGNAT). Rotating/revoking a code ends its sessions immediately. Remote links need `ALAS3_SITE_URL=https://…`. Code kinds: `shared` (Mode A), `unit` (Mode B), `admin`.

## Phases
Phase 1 (current): reglamento + liquidaciones, Gastos / Reglamento / Buscar / page viewer, access links.
Phase 2: tickets OCR + ARCA QR + matching + dashboard. Phase 3: actas + comments. Phase 4: NL→SQL Q&A.

## Workflow
- `checker` subagent (haiku): runs `make test` / `make validate`, reports pass/fail only.
- `reviewer` subagent (sonnet; opus for middleware, R2 gating, redaction, comment anonymity): read-only review after each phase.
