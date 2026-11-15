# Alas 3 – Torre 3 · Neighbour Transparency Portal — Plan & Claude Code Handoff

_Version 1.2 · 2026-11-14 · Status: ready for review (access: link-based, no IdP)_

## 1. Goal

A private website, open only to Torre 3 neighbours, that turns the building's scattered PDFs and scans into connected, searchable information:

- **Expenses (liquidaciones de expensas)**: every line item is linked to its ticket or invoice, and each record can be opened on the original scanned page.
- **BI-style questions** such as "How much did we spend on *pintura* in 2026?", "How many taxis did we reimburse to the encargado?", "Top 10 vendors" and "Which expenses have no ticket?"
- **Co-owner rules (reglamento)** as readable, searchable text, article by article, with a "ver original" link to the scanned page.
- **Committee minutes (actas)**: decisions, with links to the expenses they led to.
- **Anonymous comments** from verified neighbours.
- **Cost**: as close to USD 0/month as possible.

The UI is in **Spanish (es-AR)**. Code and docs are in English.

## 2. Key design decision: heavy work offline, a thin website online

The costly, failure-prone work (OCR, AI extraction, matching) runs **offline as a batch pipeline** on your laptop or in a GitHub Action, about once a month when the administrator sends new documents. The website only **reads** clean, pre-computed data, plus comments. Because of that:

- hosting stays inside free tiers with a wide margin
- no AI API is billed per page view
- a person reviews the data before neighbours see it, so OCR mistakes aren't published as facts

```
 admin PDFs/scans ─► [ PIPELINE (local, Python) ] ─► review queue ─► publish
                       split pages → text/OCR → QR decode            │
                       → AI extraction → classify → match            ▼
                                                     ┌─────────────────────────────┐
                                                     │ Cloudflare (free tier)      │
 neighbour ─► access link → signed cookie ─────────► │ Pages: React SPA            │
                                                     │ Pages Functions: Hono API   │
                                                     │ D1: SQLite + FTS5 search    │
                                                     │ R2: originals + page images │
                                                     │ Workers AI: Q&A (phase 4)   │
                                                     └─────────────────────────────┘
```

## 3. Hosting: recommended stack (Cloudflare, USD 0)

| Need | Choice | Free-tier fit |
|---|---|---|
| Frontend | Cloudflare Pages (static React + Vite SPA) | Static requests and bandwidth are unlimited |
| API | Pages Functions (Hono, TypeScript) | 100k requests/day, far above what about 100 neighbours generate |
| Database | Cloudflare D1 (SQLite) | 5 GB. Supports **FTS5** full-text search |
| Original PDFs + page images | Cloudflare R2, **private** bucket | 10 GB storage, **free egress** (useful for viewing scans) |
| Login, neighbours only | **Access link → signed cookie**, checked in Pages middleware (no IdP, no email) | Built on D1 + one middleware file. Works for 64 units or more |
| Natural-language Q&A (later) | Workers AI | 10,000 neurons/day free. Per third-party trackers, not used for training |

**Why not Vercel + Supabase?**

- Vercel Hobby would work: a condo portal counts as non-commercial, and Hobby is limited to non-commercial use. However, Vercel Blob is small, and you would still need separate auth, a separate database and separate storage.
- Supabase's free tier **pauses projects after 7 days without activity**. That's a bad fit for a portal neighbours open every few weeks.
- Cloudflare provides the database, file storage and AI on one free account, and serving scans costs nothing because egress is free.

**Fallback (if you prefer Next.js/Vercel):** Vercel Hobby (Next.js) + Neon Postgres (free plan: scales to zero, 0.5–1 GB) + R2 for files + Auth.js email magic links. Same data model.

**Access model (decided: access link, no IdP)**

Torre 3 has 64 apartments. Cloudflare Access's free tier stops at 50 users, so access works through a **link** instead:

1. A neighbour opens `https://<site>/acceso?k=<token>`. The token is 32+ random bytes, about 43 base64url characters.
2. `functions/_middleware.ts` looks up `sha256(token)` in `access_codes`. If the code is active, it sets an HttpOnly, Secure, SameSite=Lax cookie holding a JWT signed with `SESSION_SECRET` (valid 180 days) and **redirects to `/` so the token leaves the URL bar and history**.
3. Every other request, including the API and file downloads, checks the cookie. Without it, the visitor sees a page saying "Pedí el enlace de acceso a la comisión."

**Codes table and modes.** Both modes use the same table and code; changing mode means running a script, not writing new code:

- **Mode A, starting point:** one shared link for the whole tower, sent in the neighbours' WhatsApp group. Simplest.
- **Mode B, upgrade:** 64 per-apartment links, one per UF, delivered as a printed QR code under each door. Each one can be revoked on its own (e.g. when a tenant moves out), and abuse can be traced to one apartment's key.

**Admin.** An `admin` code type unlocks the review queue and comment moderation.

**Rotation.** `make rotate-link` disables the old shared code and prints a new one. Do this when someone moves out or the link leaks, or routinely, say every 6 months. Existing cookies stay valid until they expire unless `SESSION_SECRET` is also rotated, which logs everyone out.

**Hardening:**

- Rate-limit `/acceso` to about 10 attempts per IP per hour.
- Add `X-Robots-Tag: noindex` everywhere.
- `Referrer-Policy: no-referrer`.
- R2 is **never public**: files are only streamed through the API after the cookie is checked.

**Honest limit of a shared link:** anyone who receives a forwarded link gets in, and individual people can't be blocked. That's acceptable for building documents if the link is rotated. Switch to per-apartment links if it becomes a problem.

## 4. Ingestion pipeline (Python, run locally)

Folder convention (`data/` is **git-ignored**, because it holds personal data):

```
data/inbox/
  liquidaciones/2026-10_liquidacion.pdf
  comprobantes/2026-10_comprobantes.pdf      # scanned tickets bundled in one PDF
  reglamento/reglamento_copropiedad.pdf
  actas/2026-09-15_acta_comision.pdf
```

Steps (each step is idempotent and caches its output in `data/work/`):

1. **Inventory and split.** Hash each file and split it into pages. Render each page to WebP (~150 dpi) for the viewer. Keep the original PDF.
2. **Text layer.**
   - Born-digital pages: extract text directly with PyMuPDF, or Docling for tables.
   - Scanned pages: OCRmyPDF + Tesseract `spa`, with OpenCV deskew and contrast preprocessing. This also produces a searchable PDF.
   - Pages that still read badly: fall back to PaddleOCR (see §9).
3. **ARCA/AFIP QR decode** on ticket pages (pyzbar/OpenCV). Argentine electronic invoices must carry a QR that encodes the issue date, issuer CUIT, invoice type and number, and amount. When it's readable, those fields are **exact**, with no OCR guesswork. Decode the `?p=` base64 JSON from the QR URL.
4. **Structured extraction.** A vision-capable LLM reads each page image and its OCR text and returns **strict JSON** validated with Pydantic schemas:
   - `Ticket`: date, vendor, CUIT, invoice type/number, total, line items, payment method, keywords (e.g. "taxi", "remis")
   - `LiquidacionLine`: period, rubro, concepto, proveedor, importe, page reference
   - `ReglamentoArticle`: number, title, text, page(s)
   - `Acta`: date, attendees (roles only), topics, decisions, action items, amounts mentioned
5. **Classification.** Assign a fixed taxonomy (`taxonomy.yaml`): the administrator's own *rubros*, sub-categories and tags such as `encargado`, `movilidad/taxi`, `limpieza` and `ascensor`. Rule-based keywords run first; the LLM handles only the leftovers.
6. **Matching (expense line ↔ ticket).** Score each pair on exact or ±1% amount, same or adjacent period, and vendor/CUIT similarity (rapidfuzz). Results:
   - score ≥ 0.9: auto-link
   - 0.6–0.9: goes to the review queue
   - < 0.6: unmatched (this is a useful signal: "expenses without a ticket")
   - one line can have many tickets (e.g. "reintegro gastos encargado" = 6 taxi tickets)
7. **Validation.** Check that the sum of lines equals each rubro total and that rubros equal the liquidación total. Flag mismatches.
8. **Redaction.** Mask CUIL/DNI/CBU patterns in text. Payroll pages (the encargado's salary slips) are restricted or shown as totals only. Per-unit debt lists (morosos) are hidden by default (see §8).
9. **Review.** A small local review UI (or an admin-only page) to confirm low-confidence fields and links. Every record has `confidence` and `verified` fields, and the site shows a "sin verificar" badge on unverified data.
10. **Publish.** Generate SQL upserts → `wrangler d1 execute --remote`, and upload images and originals → `wrangler r2 object put`.

**AI cost options for extraction** (one-time backfill, then a few dozen pages a month):

- **A, USD 0:** let **Claude Code itself** do the backfill extraction in batches. It can view page images and write the JSON, using your existing subscription.
- **B, a few USD total:** a cheap vision model through the API (e.g. Claude Haiku), batched.
- **C, free API tiers** (e.g. Gemini Flash free tier): Google's own pricing page says free-tier requests may be used to improve its products. Avoid this for neighbours' personal data.

Quality gate: hand-label a **golden set of ~20 tickets + 2 liquidaciones** and measure field accuracy before running everything.

## 5. Data model (D1 / SQLite)

```sql
documents(id, kind['liquidacion','comprobantes','reglamento','acta','otro'],
          period, title, r2_key_pdf, sha256, pages, uploaded_at)
pages(id, document_id, page_no, r2_key_img, text, ocr_engine, has_qr, restricted)
periods(id 'YYYY-MM', total, document_id)
expense_lines(id, period_id, rubro, subcategoria, concepto, proveedor, cuit,
              importe, page_id, confidence, verified)
tickets(id, page_id, fecha, proveedor, cuit, tipo_cmp, pto_vta, nro_cmp,
        total, medio_pago, source['qr','llm','manual'], confidence, verified)
ticket_items(id, ticket_id, descripcion, cantidad, importe)
expense_ticket_links(expense_line_id, ticket_id, score, status['auto','verified','rejected'])
tags(id, name) ; entity_tags(entity_type, entity_id, tag_id)
reglamento_articles(id, numero, titulo, texto, page_ids_json)
actas(id, fecha, resumen, document_id)
acta_items(id, acta_id, tipo['decision','tarea','tema'], texto, importe, related_expense_ids_json)
access_codes(id, code_hash, kind['shared','unit','admin'], unit_label NULL, active,
             created_at, expires_at NULL, last_used_at, uses)
comments(id, entity_type, entity_id, body, created_at, author_key, access_code_id,
         status['visible','hidden','removed'], reports)
search_fts  -- FTS5 virtual table over page text, articles, acta items, expense conceptos
```

## 6. Website features (Spanish UI)

1. **Inicio (dashboard):** monthly spend trend, breakdown by rubro, top vendors, % of spend with a linked ticket, latest acta decisions.
2. **Gastos (explorer):** filterable table (period, rubro, tag, vendor, amount range, free text). Each line opens a side panel with the linked tickets, the page image (zoomable) and a "ver PDF original" link at the right page.
3. **Comprobantes:** ticket gallery, filterable; unlinked tickets highlighted.
4. **Preguntas frecuentes / análisis:** saved queries that answer the common BI questions, e.g. *"Taxis reintegrados al encargado"* (count, total and list by month), *"Gasto por rubro año a año"*, *"Gastos sin comprobante"*.
5. **Reglamento:** table of contents, article text, search within it, and "ver original" for each article.
6. **Actas:** timeline, decisions and tasks, and links to the related expenses.
7. **Buscar:** global FTS5 search with snippets that jump to the exact page.
8. **Comentarios** on any expense, ticket, article or acta, plus a general board.
9. **Preguntale al portal** (phase 4): natural-language question → LLM generates **read-only SQL against whitelisted views** → result table plus the SQL shown for transparency. Runs on Workers AI's free daily allocation.

## 7. Anonymous comments, done honestly

- Only people with a valid access cookie can post. Comments display as **"Vecino/a anónimo/a"**.
- Each browser gets a random `device_id` at login, stored in its session cookie. The server stores `author_key = HMAC(secret, device_id)`, plus the access code's id. That supports rate limiting (e.g. 10/day per device), letting authors delete their own comments, and hiding an abusive device's comments.
- **Mode A (shared link):** comments can't be traced to an apartment, so anonymity is strong. Abuse control is limited: clearing cookies gets a new device. Rely on reports plus rotating the link.
- **Mode B (per-apartment links):** abuse can be traced to one apartment's code, which can then be revoked. **Be transparent:** whoever runs the database could see which apartment's code posted. Say so on the "Cómo funciona" page, and agree in the comisión who (if anyone) may look.
- **Moderation:** a "Reportar" button; auto-hide after 3 reports pending review by two comisión moderators; published house rules (no insults, no naming neighbours with accusations, no personal data). Being anonymous on the site doesn't remove an author's personal legal responsibility for defamatory content, so state that in the rules.

## 8. Privacy and governance (check before launch)

- **Ley 25.326 (datos personales):** don't publish the encargado's CUIL, payroll detail or bank data. Don't publish per-unit debts by name or unit without a decision from the comisión/asamblea. Mask DNIs/CUILs in OCR text.
- **Get the comisión's (ideally the asamblea's) approval** to publish the documents on a private portal, and tell the administrator. Co-owners' right to the building's accounts supports transparency, but where and how the documents are shared should be agreed.
- Keep the repo **private**, keep `data/` out of git, and back up D1 (`wrangler d1 export`) and R2 monthly.
- _(Not legal advice. Worth a quick review against the reglamento itself.)_

## 9. Open-source tools to evaluate

Research run on 2026-11-14. Verify licences and versions when installing.

**OCR and parsing (all run on a normal laptop, no GPU):**

| Tool | Licence | Use it for |
|---|---|---|
| **OCRmyPDF + Tesseract `spa`** | MPL-2.0 / Apache-2.0 | **Default.** Scanned PDFs become searchable PDFs plus text. Add OpenCV deskew and contrast preprocessing for phone photos. |
| **PaddleOCR** | Apache-2.0 | Fallback for tickets Tesseract reads badly. Heavier install. |
| **Docling** (IBM) | MIT | Born-digital PDFs with tables: liquidaciones, reglamento, actas. |
| MinerU | licence not confirmed | Optional. CPU mode needs about 8 GB RAM. |
| olmOCR | Apache-2.0 | Skip: needs an NVIDIA GPU with ≥ 12 GB. |
| Marker / Surya | code Apache-2.0, weights Open RAIL-M | Probably allowed for a neighbours' group, but check the weights licence first. |

**ARCA invoice QR:** no dedicated open-source decoder was found. Implement it in about 20 lines:

1. Read the QR with pyzbar or OpenCV.
2. Take the `p=` parameter from the URL and base64-decode it into JSON.
3. Read the fields `ver, fecha, cuit, ptoVta, tipoCmp, nroCmp, importe, moneda, ctz, tipoDocRec, nroDocRec, tipoCodAut, codAut`. (These field names come from PyAr/pyafipws `pyqr.py`. Confirm them against ARCA's spec at https://www.afip.gob.ar/fe/qr/.)

**Ready-made document managers: considered and rejected as the core.**

- **Paperless-ngx** (GPL-3.0) gives OCR, tags and full-text search. It has **no** line-item extraction, BI or anonymous comments, and it needs an always-on Docker host with about 4 GB RAM.
- No reliable USD 0 always-on host was found:
  - Fly.io has no free tier for new organisations.
  - Render's free tier has 512 MB RAM.
  - Google's e2-micro is too small.
  - Oracle Always Free ARM limits reportedly changed in 2026, which could not be confirmed.
- Paperless-ngx is still an option as a **private archive on a spare home PC** for whoever runs the pipeline, but not as the neighbours' portal.

**"Chat with your docs" apps (AnythingLLM MIT, Open WebUI):**

- Fine for questions about the rules, but they **can't sum money reliably**: totals need SQL, not retrieval (RAG).
- Hence the design in §6.9: NL→SQL on whitelisted views for amounts, plus FTS5 snippets for text questions.

**BI tools:**

- **Evidence** (MIT) builds a **static** BI site, a good alternative if you'd rather write dashboards as SQL + Markdown than build them in React. It can deploy to Cloudflare Pages behind the same access-link middleware.
- Metabase (AGPL) and Superset (Apache-2.0) need a server, so they're rejected for USD 0.

**Condo software:**

- open-condo-software/condo (MIT) runs on Node + Postgres + Redis, has no clear resident portal and no Spanish. It's too heavy.
- pHKondo looks dormant.
- Argentine commercial apps such as Octopus exist but aren't free.
- **Conclusion:** a small custom app is the right call.

## 10. Phased delivery (for Claude Code)

Repo layout:

```
alas3-portal/
  CLAUDE.md                # this plan, condensed + conventions
  pipeline/                # Python 3.12, uv, Pydantic, PyMuPDF, ocrmypdf, pyzbar, rapidfuzz
    alas3/{ingest,ocr,qr,extract,classify,match,validate,redact,publish}.py
    schemas.py  taxonomy.yaml  golden/  tests/
  web/                     # Vite + React + TS, TanStack Table, ECharts/Recharts
    functions/api/[[route]].ts   # Hono API on Pages Functions
  db/migrations/*.sql
  data/                    # git-ignored: inbox/, work/, out/
  Makefile                 # make ingest | review | publish | backup
```

| Phase | Scope | Done when |
|---|---|---|
| **0. Prep** (you) | Collect all PDFs; get comisión approval; create Cloudflare account; decide where the link will be shared (WhatsApp group?) | Inbox populated |
| **1. MVP read-only** | Pipeline for reglamento + liquidaciones (born-digital first); D1 schema; site with Reglamento, Gastos table, global search, page viewer; access-link middleware (Mode A) + `make new-link` / `make rotate-link` / `make admin-link` | A neighbour opens the link, reads article X with its original scan, and filters expenses by rubro. A request without the cookie, including a direct file URL, gets nothing |
| **2. Tickets + links** | OCR + QR + AI extraction for comprobantes; matching + review queue; dashboard and saved analyses (taxis, by rubro, without ticket) | ≥ 90% field accuracy on the golden set; "taxis to encargado" answer matches a manual count |
| **3. Actas + comments** | Acta extraction + cross-links; comments with HMAC, reports and moderation | Two moderators can hide/restore; comments show as anonymous |
| **4. Ask + routine** | NL→SQL Q&A on whitelisted views; `make monthly` routine (optionally a GitHub Action); backups | New month published in < 30 min of human time |

**Prompt to start Claude Code:**
> (Run with `/model opusplan` and start in plan mode.) Read `PLAN.md` and `design/DESIGN.md`. First create the `checker` (haiku) and `reviewer` (sonnet, read-only) subagents described in §10b. Use `design/theme.css` as the Tailwind v4 theme. Scaffold the repo exactly as in §10, write `CLAUDE.md` from it, implement Phase 1 only, and stop for review. Use the sample files in `data/inbox/`. UI text in Spanish (es-AR), code in English. Never commit anything under `data/`.

## 10b. Development workflow: which model does what (Claude Code)

| Role | Model | How in Claude Code |
|---|---|---|
| Plan each phase or feature | **Opus** | `/model opusplan`: Opus while in plan mode, then it switches to Sonnet automatically for execution |
| Implement | **Sonnet** | Same session (the execution half of `opusplan`) |
| **Mechanical checks** | **Haiku** | Subagent `.claude/agents/checker.md`, `model: haiku`. Runs lint, type-check, tests and `make validate` (sum checks, golden-set accuracy) and reports pass/fail with the failing output. It doesn't judge design |
| **Code review / verification** | **Sonnet**, or **Opus** for the sensitive parts | Subagent `.claude/agents/reviewer.md`, `model: sonnet`, `tools: Read, Grep, Glob, Bash` (read-only). Run it after each phase with a fresh context, so it isn't grading its own work |
| Security review: access-link middleware, R2 file gating, redaction, comment anonymity | **Opus** | Same reviewer with `model: opus`, once before launch and whenever those files change |

Rules:
- Plan per **phase/feature**, not per tiny task: a one-line fix doesn't need an Opus plan.
- Haiku checks only things with an objective pass/fail (commands, numbers, schemas). A smaller model reviewing a larger model's code tends to approve subtle bugs, so judgement calls go to Sonnet or Opus.
- The pipeline's runtime extraction model (§4) is a separate choice, made by measuring accuracy on the golden set, not by these roles.

## 11. Monthly routine (after launch)

1. Save the administrator's new PDFs into `data/inbox/…`
2. `make ingest` → `make review` (confirm flagged items, ~15–20 min) → `make publish`
3. Optional: post a "Liquidación de octubre publicada" note on the comments board.

## 12. Open questions

1. ~~How many logins?~~ **Decided:** Torre 3 has 64 apartments. Access is by link, no IdP: start with one shared link (Mode A), with per-apartment links (Mode B) available without code changes.
2. How many months and pages exist now (backfill size)?
3. Does the administrator send born-digital PDFs or only scans? (Born-digital makes extraction much more accurate.)
4. Should each neighbour see "your unit's share" (needs each UF's coefficient from the reglamento)?
5. Who will moderate comments, and who holds the admin role?
