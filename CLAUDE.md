# Torre 3 portal (Alas 3) — Claude Code notes

Private, read-mostly transparency portal for the 64 units of Torre 3. Full spec: `PLAN.md`. Visual spec: `design/DESIGN.md` + `design/theme.css`.

## Hard rules
- **Never commit anything under `data/`** (personal data: scans, OCR text, extracted rows). It is git-ignored; keep it that way.
- UI text in **Spanish (es-AR)**; code, comments, docs in English.
- Money: `Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS'})`. Dates: `14 nov 2026`.
- R2 is never public. Every file goes through `/api/files/*` after the cookie check.
- Privacy is fail-closed (`pipeline/alas3/redact.py`, `ingest.py`): payroll pages, debt listings and unreadable scans are `restricted` (never served or indexed); the "Unidades en mora" block of a liquidación is blacked out; person CUIL/DNI/CBU are masked in every published string AND blacked out in the PDF/images. Only `data/work/docs/*/public.pdf` and renders made from it are ever uploaded.
- Manual review overrides: `data/work/restrict.json` → `{"<sha16>": {"restrict": [pages], "allow": [pages]}}`, then `make ingest ARGS=--force` and publish.
- Every QR code found on a receipt page is blacked out in `public.pdf` after decoding (invoice QRs encode the issuer CUIT = a person's CUIL for monotributo vendors). A page that mentions a CAE but has no decoded QR (after a 400/600 dpi retry) and no located 1D barcode is `restricted` (`qr_not_located`); a person CUIT decoded from a QR is searched for on the page and blacked out, or the page is restricted. Receipts read only from restricted pages are never published.
- Scanned/photographed receipt pages are `restricted` (`unchecked_scan`) until listed in the transcription's `checked` map (`{page: [{x0,y0,x1,y1,motivo}]}`, fractions of the displayed page): the areas are blacked out in the image and their OCR text dropped. A QR that encodes another voucher (a vendor reprinting an old QR) goes in `ignore_qr`. Insurance policies naming an insured person are `restricted` (`personal`).
- Only `config.PHASE_KINDS` are ingested/published (now: reglamento, liquidacion, comprobantes).
- Receipts: ARCA QR fields are exact; the rest comes from `data/work/extract/<sha16>.tickets.json` (Claude Code transcribes page images; `alas3 ingest` reports pages still to transcribe). Human decisions live in `data/work/review.json` (`make review`, 127.0.0.1 only). Links are recomputed on every publish from `match.py` + review.json.
- Bank statements inside receipts PDFs ("RESUMEN DE CUENTA CORRIENTE", `bank.py`) are parsed from page text and used only if opening balance + movements = closing balance and every "Saldo al" checkpoint. Credit rows (owners' payments) are blacked out on the published page (image, PDF, text, search); the full text stays private in `raw/pNNN.bank.txt` for the balance check. Debits become payment evidence (`bank_movements`, `expense_payment_links`, decisions in `review.json` → `payments`); salary/refund rows are blacked out on the page too and published as "Pago de haberes" / "Reintegro o devolución"; commissions/taxes are grouped into one "Gastos bancarios" movement. A line is backed by a covered receipt OR a covered payment.
- Ids of expense lines and receipts are stable hashes (`ids.py`): never switch back to delete-and-reinsert.
- Data with `verified = 0` shows a "Sin verificar" tag.

## Layout
```
pipeline/      Python 3.12 (uv). alas3/{ingest,ocr,qr,extract,receipts,classify,match,validate,review,redact,publish,links}.py
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
- `make ingest` → `make validate` → `make match` / `make review` → `make publish-local` | `make publish`
- `make dev` — build SPA and run `wrangler dev` on :8788 with local D1/R2
- `make new-link [LOCAL=1] [UNIT=UF12]`, `make rotate-link`, `make admin-link`
- `make test` — pytest + ruff + vitest + tsc
- `make backup` — D1 export of base tables (FTS excluded; restore = migrations + dump + db/rebuild_fts.sql)

## Access model
`/acceso?k=<token>` → `sha256(token)` looked up in `access_codes` (active, unexpired) → HS256 JWT cookie `t3s` (180 days, HttpOnly, Secure, SameSite=Lax) → 302 `/`. Each request re-checks the JWT **and** that the code is still active (revocation works immediately). `/acceso` allows 10 FAILED attempts/h per hashed IP (successes never count: CGNAT). Rotating/revoking a code ends its sessions immediately. Remote links need `ALAS3_SITE_URL=https://…`. Code kinds: `shared` (Mode A), `unit` (Mode B), `admin`.

## Phases
Phase 1 (done): reglamento + liquidaciones, Gastos / Reglamento / Buscar / page viewer, access links.
Phase 2 (done): receipts (ARCA QR + transcription), matching + local review, dashboard (Recharts; palette order validated in `web/src/components/charts.tsx`), Comprobantes, Análisis.
Phase 3: actas + comments. Actas are photos of a handwritten book: one acta can span several images, so segment across image boundaries. Phase 4: NL→SQL Q&A.

## Workflow
- `checker` subagent (haiku): runs `make test` / `make validate`, reports pass/fail only.
- `reviewer` subagent (sonnet; opus for middleware, R2 gating, redaction, comment anonymity): read-only review after each phase.
