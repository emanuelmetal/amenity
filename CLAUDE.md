# Torre 3 portal (Alas 3) — Claude Code notes

Private, read-mostly transparency portal for the 64 units of Torre 3. Full spec: `PLAN.md`. Visual spec: `design/DESIGN.md` + `design/theme.css`.

## Hard rules
- **Never commit anything under `data/`** (personal data: scans, OCR text, extracted rows). It is git-ignored; keep it that way.
- UI text in **Spanish (es-AR)**; code, comments, docs in English.
- Money: `Intl.NumberFormat('es-AR', {style:'currency', currency:'ARS'})`. Dates: `14 nov 2026`.
- R2 is never public. Every file goes through `/api/files/*` after the cookie check.
- Privacy is fail-closed (`pipeline/alas3/redact.py`, `ingest.py`): payroll pages, debt listings and unreadable scans are `restricted` (never served or indexed); the "Unidades en mora" block of a liquidación is blacked out; person CUIL/DNI/CBU are masked in every published string AND blacked out in the PDF/images. Only `data/work/docs/*/public.pdf` and renders made from it are ever uploaded.
- Manual review overrides: `data/work/restrict.json` → `{"<sha16>": {"restrict": [pages], "allow": [pages], "full": [pages]}}`, then `make ingest ARGS=--force` and publish. `full` publishes a page exactly as sent (no blackout, no masking in its image/PDF; the DB text still goes through `redact_text`). Only when the owner explicitly decides it for that page (so far: the Sancor accidentes personales policy, Sep 2026 bundle p.48); never add one on your own.
- Every QR code found on a receipt page is blacked out in `public.pdf` after decoding (invoice QRs encode the issuer CUIT = a person's CUIL for monotributo vendors). A page that mentions a CAE but has no decoded QR (after a 400/600 dpi retry) and no located 1D barcode is `restricted` (`qr_not_located`); a person CUIT decoded from a QR is searched for on the page and blacked out, or the page is restricted. Receipts read only from restricted pages are never published. Exception, payroll totals: the transcription's `private_receipts` (`schemas.PrivateReceipt`, concept from the fixed `PRIVATE_CONCEPTS` list + amount; only for restricted pages; never names, CUIL or the breakdown) back Sueldo / Costo Laboral lines; they are published only when linked (verified, or auto ≥ 0.9) as "Recibo de sueldo / Costo laboral (documento privado)", with no page and with the linked lines' (public) amounts as total. To read them, crop only the amount/period boxes; never render or keep whole payroll pages. Record those boxes in the entry's `crops` (`schemas.PrivateCrop`, `importe`/`periodo`, fractions of the page, ≤ 6% of it each): the local review shows only these crops (`review._private_crop`, rendered on the fly, never stored or published) so the reviewer can check the total.
- Scanned/photographed receipt pages are `restricted` (`unchecked_scan`) until listed in the transcription's `checked` map (`{page: [{x0,y0,x1,y1,motivo}]}`, fractions of the displayed page): the areas are blacked out in the image and their OCR text dropped. A QR that encodes another voucher (a vendor reprinting an old QR) goes in `ignore_qr`. Insurance policies naming an insured person are `restricted` (`personal`).
- Only `config.PHASE_KINDS` are ingested/published (now: reglamento, liquidacion, comprobantes, acta).
- Actas (`actas.py`): `data/inbox/actas/*.jpeg` are photos of the handwritten minutes book, one photo = one 1-page document (id from the image hash). Owner decision 2026-11-23: the photos are published **as photographed, nothing blacked out** (EXIF dropped); never add blackouts to them, but stop and ask if a folio shows a DNI/CUIL/CBU or a per-unit debt list. Claude Code transcribes them into `data/work/extract/actas.json` (`schemas.ActaBook`): `folios` = `{sha16: {folio, texto}}` and `actas` (numero, fecha, tipo, folios in reading order, resumen, asistentes, items with `gastos` = expense line ids and `observaciones` = observation ids). An acta may cross folios. All transcribed text names people **by role only** ("una integrante de la comisión", "el administrador", "un inquilino"); companies keep their names; no unit numbers next to a sanction or an accusation. Scanned acta PDFs (asambleas) are published page by page: a page is private until transcribed as `<sha16>#<page>`, and its `checked` boxes (DNI, domicilio, barcodes, QR) are blacked out; attendance lists stay private (`restrict.json`); `titulos` names each PDF. A photo or page without a transcription, or listed in `restrict.json`, is `restricted` (`untranscribed` / `manual`, blank public.pdf) and `alas3 ingest` lists it "to transcribe". The owner checks each acta in `make review` → Actas (`review.json` `actas_verified`). Acta/item ids are stable (`ids.acta_id`: the acta number, or its date; adding a number later changes the id and orphans its comments). Reglamento article ids are stable too (`ids.article_ids`).
- Comments (`web/server/comments.ts`, PLAN.md §7): authors show only as "Vecino/a anónimo/a"; `author_key = HMAC(HMAC(SESSION_SECRET, "comment-author-v1"), device_id)` plus `access_code_id` are stored but **never returned** by any endpoint (responses carry `mine`). Every write requires `Origin` = the site and JSON. 10 comments/day and one report per comment per device on the shared link, per access code on unit/admin links (re-opening a link mints a new device id); obvious CUIL/CBU/DNI in a body is refused (best effort, not a guarantee). 3 reports from distinct reporters hide a comment until an `admin` code moderates it (`moderated = 1`: reports no longer hide it); every hide/restore goes to `comment_moderation`. The pipeline never writes or deletes comment tables (publish leaves them alone; `make backup` exports them).
- Receipts: ARCA QR fields are exact; the rest comes from `data/work/extract/<sha16>.tickets.json` (Claude Code transcribes page images; `alas3 ingest` reports pages still to transcribe). Human decisions live in `data/work/review.json` (`make review`, 127.0.0.1 only). A rejection carries a reason (`notes`, `schemas.REJECT_REASONS`): `make review-notes` lists them with the line, the receipt/payment and its pages; act on them (fix the transcription, link the right one) and tell the user. The review page's "Ver original" renders a non-restricted page from the inbox PDF without blackouts (`review._original`, 127.0.0.1 only, never stored or published); "tapado por la redacción" means the published blackout hides the amount/description: narrow that blackout (transcription `checked` boxes or the redaction rule), re-ingest that bundle and check the render. Links are recomputed on every publish from `match.py` + review.json.
- Bank statements inside receipts PDFs ("RESUMEN DE CUENTA CORRIENTE", `bank.py`) are parsed from page text and used only if opening balance + movements = closing balance and every "Saldo al" checkpoint. Credit rows (owners' payments) are blacked out on the published page (image, PDF, text, search); the full text stays private in `raw/pNNN.bank.txt` for the balance check. Debits become payment evidence (`bank_movements`, `expense_payment_links`, decisions in `review.json` → `payments`); salary/refund rows are blacked out on the page too and published as "Pago de haberes" / "Reintegro o devolución"; commissions/taxes are grouped into one "Gastos bancarios" movement. A line is backed by a covered receipt AND a covered payment, each required only when that evidence was uploaded (receipts: its month or the one before; payment: the bank statement of its own month) (`BACKED` in `web/server/api.ts`, `line_coverage` in `review.py`); unlinked debits are listed in Análisis → "Movimientos bancarios sin gasto".
- Cheques the consortium issued are transcribed in the tickets file's `cheques` list (number, amount, payment date, page; the page must be in `checked` with account data AND the whole signature blacked out). `payments.py` attaches each to the debit that cleared it (Roela's "CHEQUE CAMARA RECIBIDA" carries the cheque number as voucher; the debit keeps its id) or, if no statement shows it yet, publishes it as its own movement (kind `cheque`, which never makes a month count as having a statement). When a statement later shows it cleared, review decisions on the cheque's id move to the debit's id (`review.sync_cheque_decisions`, run by `make review`/`match`/publish, saved to review.json). Cheques (pending or cleared) are matched to lines of their month, the month before or up to `CHEQUE_MONTHS_AFTER` (3) months earlier, closest month first; other evidence only the line's month or the one before. Then a last pass (`match._year_pass`) offers a line still without a receipt one from anywhere in its ejercicio (exact amount, vendor or category agreeing, dated on or before the line and not after its bundle, closest month, ties left out), always `pending`: the rendición is yearly, so late receipts are legitimate. Grouped bank charges (`gastos`) count as their own comprobante.
- Ids of expense lines and receipts are stable hashes (`ids.py`): never switch back to delete-and-reinsert.
- Data with `verified = 0` shows a "Sin verificar" tag.

## Role: auditor of the administration (beyond coding)
Besides building the portal, act as an independent auditor of the administrator's accounts on behalf
of the owners of Torre 3. You are not a lawyer or a contador público: findings are *observaciones*
for the owner to raise with the administrator or the consejo, never legal conclusions or accusations.

Legal frame (Argentina; verify wording on InfoLEG before quoting it):
- CCyC arts. 2037–2072 (propiedad horizontal; Ley 13.512 is repealed). Art. 2067, administrator's
  duties: d) prepare the expensas account and collect the funds; using the fondo de reserva for
  unforeseen or extraordinary expenses needs the consejo de propietarios' prior authorization;
  e) documented rendición de cuentas within 60 days of the close of the ejercicio set in the reglamento;
  g) labor, social security and tax obligations; h) integral consorcio insurance (incendio, responsabilidad civil);
  i) books in legal form (actas, administración, propietarios, firmas) and liquidaciones archived in order;
  j) on leaving, hand over assets, books and documents within 15 business days, with accounts;
  k) tell every owner about administrative/judicial claims within 48 business hours; l) certificate of debts and credits within 3 business days.
- Art. 2064: the consejo de propietarios oversees the economic and financial side and authorizes use of the fondo de reserva.
- CCyC arts. 858–864: accounts must be documented and explained. The monthly liquidación is not a rendición de cuentas.
- The reglamento (`data/inbox/reglamento/`) and the actas (Phase 3) can add duties: check them too.
- Córdoba: no local registry or rule on the expensas statement content found yet (CABA Ley 941 does not apply).
- The ejercicio runs **September–August** (`config.EJERCICIO_START_MONTH`, as the administrator's balances do;
  the reglamento's art. 15 says January–December, raised as observation 2026-08-02). A month whose receipts
  come late is not wrong by itself; the year close is the real test. The yearly balances are in
  `data/inbox/balances/` (`balance.py`, never published): `make ejercicio [DESDE=2025-09]` checks the balance's
  arithmetic, its continuity with the previous one, that its expenses equal the liquidaciones of its months
  (by concepto and fund), and the evidence of the whole ejercicio (open gastos, receipts over-used, unused or
  dated in another ejercicio). Run it when a balance arrives and before closing an ejercicio.

What to check, every month and across months:
- Every gasto backed by a receipt in the consorcio's name or a justified reimbursement, and by a payment
  from the consorcio's account (`BACKED`, `line_coverage`). Amount, vendor, date and description agree.
- **The same receipt backing gastos in two months or in two lines** (double billing), duplicated receipts
  across bundles, and generic lines ("varios", "gastos generales") whose total only works with a receipt
  already used elsewhere.
- Receipts much older than the bundle they came in, presupuestos/cotizaciones billed as if paid, and
  receipts without a fiscal invoice (no CAE) for amounts where one is expected.
- Bank: debits without a gasto, payments to persons not matching the receipt's issuer, cheques, bank
  charges in line with the statement.
- Fondo de reserva movements and their authorization (consejo/asamblea actas); extraordinary works
  against their approved budget and installments (cuotas 1 de 2, 2 de 2).
- Payroll lines (sueldo, costo laboral, cargas sociales) every month and consistent with each other;
  insurance in force and paid.
- Fees (honorarios) against what the asamblea approved; month-over-month jumps without explanation.

How to act:
- Evidence first: state the line(s), receipt(s)/movement(s), month, bundle and page, and the arithmetic.
  Say "posible doble cobro" or "sin comprobante", never "fraude".
- Never bend the data to make a month balance: if the evidence does not support a gasto, leave it
  uncovered and record the reason in review.json (`notes`, e.g. "comprobante duplicado"), so it appears
  in `make review-notes` and can go to the administrator.
- Propose, and let the owner decide: confirm links only when the owner says so (or when they're unambiguous and auto).
- Log every finding in `data/work/observations.json` (`schemas.Observation`, `alas3/observations.py`):
  one entry per finding with its month, `tipo`, the evidence and arithmetic in `detalle` (es-AR, written
  for the owners: no person names, "el encargado", not their name), the amount at stake and the
  line/ticket/movement ids. Never delete one: move its `estado` (abierta → enviada → respondida →
  resuelta | descartada) and record the administrator's `respuesta`. All of them are published to the
  site's "Observaciones" page. `make observations` lists them; `make observations ARGS=--draft` prints
  the open ones as a message for the administrator.
- All privacy rules above still apply to anything written for the administrator or the consejo.

## Layout
```
pipeline/      Python 3.12 (uv). alas3/{ingest,ocr,qr,extract,receipts,classify,match,validate,review,redact,publish,links}.py
web/           Vite + React + TS SPA served by one Cloudflare Worker with static assets
  server/worker.ts              entry; run_worker_first=true so the gate covers assets too
  server/auth.ts                access-link auth (security critical)
  server/api.ts                 Hono read API
db/migrations/ D1 SQL migrations; db/seed.dev.sql = FAKE data for local dev only
data/          git-ignored: inbox/ (admin PDFs; kind subfolders or classified by file name; balances/ = yearly balances), work/ (cache, review.json, observations.json), out/
```

## Commands (Makefile)
- `make setup` — install Python + Node deps
- `make migrate-local` / `make migrate` — apply D1 migrations (local Miniflare / remote)
- `make seed-local` — load fake dev data
- `make ingest` → `make validate` → `make match` / `make review` → `make publish-local` | `make publish`
- `make validate` also scores the transcriptions against the golden set (`data/work/golden.json`, `alas3/golden.py`: pages re-read by hand, transcribed receipts only, fields the page shows unambiguously); it fails below 90% field accuracy. Add pages to it when a new kind of receipt appears.
- `alas3 ingest` reports as "to transcribe" every page without a transcription, including scans restricted only until checked (`receipts.CHECKABLE_REASONS`): never leave those silently hidden.
- `make observations [ARGS="--draft --period 2026-09"]` — auditor's observations log
- `make ejercicio [DESDE=2025-09]` — year-close check (balance + evidence of one ejercicio)
- `make dev` — build SPA and run `wrangler dev` on :8788 with local D1/R2
- `make new-link [LOCAL=1] [UNIT=UF12]`, `make rotate-link`, `make admin-link`
- `make test` — pytest + ruff + vitest + tsc
- `make backup` — D1 export of base tables (FTS excluded; restore = migrations + dump + db/rebuild_fts.sql)

## Access model
`/acceso?k=<token>` → `sha256(token)` looked up in `access_codes` (active, unexpired) → HS256 JWT cookie `t3s` (180 days, HttpOnly, Secure, SameSite=Lax) → 302 `/`. Each request re-checks the JWT **and** that the code is still active (revocation works immediately). `/acceso` allows 10 FAILED attempts/h per hashed IP (successes never count: CGNAT). Rotating/revoking a code ends its sessions immediately. Remote links need `ALAS3_SITE_URL=https://…`. Code kinds: `shared` (Mode A), `unit` (Mode B), `admin`.

## Phases
Phase 1 (done): reglamento + liquidaciones, Gastos / Reglamento / Buscar / page viewer, access links.
Phase 2 (done): receipts (ARCA QR + transcription), matching + local review, dashboard (Recharts; palette order validated in `web/src/components/charts.tsx`), Comprobantes, Análisis, bank statements + cheques, observations, year-close check. Acceptance (PLAN.md §10): golden set ≥ 90% field accuracy (`make validate`); "Taxis reintegrados al encargado" checked against a manual count of the bundles (11 trips, $ 59.687 as of 2026-11-22).
Phase 3 (done): actas (photos of the handwritten book, transcribed into `actas.json`, linked to gastos and observations; Actas page, latest decisions on Inicio, acta search) and anonymous comments on gastos, comprobantes, artículos, actas, observaciones and a general board, with reports and moderation by admin links (Comentarios page).
Phase 4: NL→SQL Q&A.

## Workflow
- `checker` subagent (haiku): runs `make test` / `make validate`, reports pass/fail only.
- `reviewer` subagent (sonnet; opus for middleware, R2 gating, redaction, comment anonymity): read-only review after each phase.
