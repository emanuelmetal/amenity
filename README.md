# amenity: Torre 3 portal

A private, read-only website for the 64 units of Torre 3 (Alas III). Neighbours can read the building's rules and see where the expenses go. It has these sections:

- Inicio: a dashboard with income vs expenses per month, spending by rubro, the main vendors, and how much of the spending has a receipt.
- Gastos: the expense lines of each monthly liquidación, by rubro and category, each with the receipts that back it.
- Comprobantes: the invoices, receipts and tickets the administrator handed over, linked to the expense lines.
- Análisis: saved answers to common questions (taxis paid to the encargado, spending by rubro per year, expenses without a receipt).
- Reglamento: the Reglamento Interno and the Reglamento de Copropiedad, article by article.
- Buscar: full-text search across all of it.
- Page viewer: every figure links back to the scanned page it came from.

There are no accounts. Access is by secret link. The UI is in Spanish (es-AR).

The full spec is in `PLAN.md` and the visual design in `design/`. `CLAUDE.md` holds the working rules for this repo.

## How it works

A Python pipeline (`pipeline/`) reads the administrator's PDFs. It OCRs scans, extracts expense lines and articles, and hides personal data. It then publishes the result to Cloudflare: D1 holds the data and a private R2 bucket holds the redacted PDFs and page images. A single Cloudflare Worker (`web/`) serves the React app and a read-only API. Every request, static files included, goes through the access check.

## Privacy

`data/` holds the original PDFs, OCR text and extracted rows. It is git-ignored and must never be committed.

The pipeline fails closed:

- Pages are restricted and never served or indexed when they are payroll slips, debt listings, scans without readable text, or pages where a personal ID couldn't be located for blacking out.
- The "Unidades en mora" block of a liquidación is blacked out in the PDF and image and dropped from the text.
- Personal CUIL, DNI and CBU numbers are masked in all published text and blacked out in the PDF and images. Company CUITs stay visible.
- Every QR code on a receipt is blacked out after it is read: an invoice QR encodes the issuer's CUIT, which for monotributo vendors is a person's CUIL.
- Only the redacted `public.pdf` and images rendered from it are uploaded. R2 is never public.

To override a page by hand, edit `data/work/restrict.json`:

```json
{ "<sha16>": { "restrict": [3, 4], "allow": [7] } }
```

then run `make ingest ARGS=--force` and publish again.

## Requirements

- Node 22 and pnpm 10
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for the pipeline)
- Tesseract with Spanish data, and OCRmyPDF: `brew install tesseract tesseract-lang ocrmypdf`
- A Cloudflare account, only for the real deployment

## Running locally

```sh
make setup           # Python and Node deps; creates web/.dev.vars with a random SESSION_SECRET
make migrate-local   # create the local D1 schema
make seed-local      # optional: fake data to try the UI
make dev             # build the app and serve it on http://localhost:8788
make new-link LOCAL=1
```

Open the printed `/acceso?k=…` link to log in. Without it every page shows "Pedí el enlace de acceso a la comisión."

## Adding documents

Put the PDFs in `data/inbox/`, either in a kind folder (`reglamento/`, `liquidaciones/`, `comprobantes/`) or at the root, where the file name decides the kind. Then:

```sh
make ingest          # OCR, QR codes, extract, redact (cached by file hash)
make validate        # expense lines add up to the total, and the account summary balances
make match           # receipt coverage per month
make review          # local page on http://127.0.0.1:8790 to check receipts and links
make publish-local   # or `make publish` for the real site
```

Reglamentos, liquidaciones and receipts are published; actas wait for phase 3. When a document can't be parsed automatically, you can write its content as JSON in `data/work/extract/<sha16>.json`. It is checked against the same schemas.

### Receipts

Electronic invoices are read from their ARCA QR code, so date, CUIT, number and total are exact. Everything else (vendor, description, items, and every field of a paper receipt) comes from a transcription in `data/work/extract/<sha16>.tickets.json`, written by reading the page images (Claude Code does it from the images) and checked in `make review`. `alas3 ingest` reports how many pages are still to transcribe.

Receipts are matched to expense lines automatically: same amount, several receipts that add up to one line, or one receipt that covers several lines. Uncertain matches wait in `make review`, where you can also confirm, reject, or link any receipt to any line by hand. Decisions are saved in `data/work/review.json` and applied on the next publish.

## Access links

```sh
make new-link        # shared link for all neighbours
make rotate-link     # replace the shared link; old sessions end at once
make admin-link
make unit-link UNIT=UF12
make revoke-link ID=3        # or UNIT=UF12
make list-links
```

Add `LOCAL=1` to work on the local database. Links for the real site need `ALAS3_SITE_URL=https://…`. Only a hash of each token is stored, so a link is shown once, when it's created. A session lasts 180 days, and revoking its code ends it immediately.

## Deploying

Nothing has been deployed yet. The first time:

```sh
cd web
pnpm exec wrangler login
pnpm exec wrangler d1 create torre3            # put the database_id in web/wrangler.toml
pnpm exec wrangler r2 bucket create torre3-files
pnpm exec wrangler secret put SESSION_SECRET   # 64 random hex chars: openssl rand -hex 32
cd ..
make migrate
make publish
make deploy
ALAS3_SITE_URL=https://<your-site> make new-link
```

After that, publishing new documents only needs `make ingest validate publish`, and code changes need `make deploy`. `make backup` exports the database to `data/backups/`.

## Tests

`make test` runs ruff, pytest, the TypeScript build check and vitest. The tests use generated PDFs and invented data only.

## Layout

```
pipeline/   Python pipeline (alas3/: ingest, ocr, qr, extract, receipts, classify, match, validate, review, redact, publish, links)
web/        Vite + React app and the Worker (server/worker.ts, auth.ts, api.ts)
db/         D1 migrations, FTS rebuild, fake seed data
design/     design notes and theme tokens
data/       git-ignored: inbox/, work/, out/
```

## Roadmap

Phases 1 and 2 are done: reglamento, liquidaciones, receipts matched to expense lines, and the dashboard. Next: asamblea minutes and comments (phase 3), then questions in plain Spanish (phase 4).

## License

Apache 2.0, see `LICENSE`.
