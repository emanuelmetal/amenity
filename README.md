# amenity: Torre 3 portal

A private, read-only website for the 64 units of Torre 3 (Alas III). Neighbours can read the building's rules and see where the expenses go. It has these sections:

- Gastos: the expense lines of each monthly liquidación, by rubro and category.
- Reglamento: the Reglamento Interno and the Reglamento de Copropiedad, article by article.
- Buscar: full-text search across both.
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
- Only the redacted `public.pdf` and images rendered from it are uploaded. R2 is never public.

To override a page by hand, edit `data/work/restrict.json`:

```json
{"<sha16>": {"restrict": [3, 4], "allow": [7]}}
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

Put the PDFs in `data/inbox/`, either in a kind folder (`reglamento/`, `liquidaciones/`) or at the root, where the file name decides the kind. Then:

```sh
make ingest          # OCR, extract, redact (cached by file hash)
make validate        # check that expense lines add up to the liquidación total
make publish-local   # or `make publish` for the real site
```

Phase 1 only publishes reglamentos and liquidaciones. When a document can't be parsed automatically, you can write its content as JSON in `data/work/extract/<sha16>.json`. It is checked against the same schemas.

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
pipeline/   Python pipeline (alas3/: ingest, ocr, extract, classify, validate, redact, publish, links)
web/        Vite + React app and the Worker (server/worker.ts, auth.ts, api.ts)
db/         D1 migrations, FTS rebuild, fake seed data
design/     design notes and theme tokens
data/       git-ignored: inbox/, work/, out/
```

## Roadmap

Phase 1 is done. Next: receipts with ARCA QR codes matched to expense lines (phase 2), asamblea minutes and comments (phase 3), and questions in plain Spanish (phase 4).

## License

Apache 2.0, see `LICENSE`.
