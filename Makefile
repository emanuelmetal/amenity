# Torre 3 portal. See CLAUDE.md. LOCAL=1 targets local wrangler state.
.PHONY: setup migrate migrate-local seed-local ingest validate review match observations ejercicio publish publish-local build dev deploy \
        new-link rotate-link admin-link unit-link revoke-link list-links backup review-notes test test-py test-web monthly ipc

PY := cd pipeline && uv run alas3
LOCALFLAG := $(if $(LOCAL),--local,)
WR := cd web && pnpm exec wrangler

setup:
	cd pipeline && uv sync
	cd web && pnpm install
	test -f web/.dev.vars || echo "SESSION_SECRET=$$(openssl rand -hex 32)" > web/.dev.vars

migrate:
	$(WR) d1 migrations apply torre3 --remote
	$(WR) d1 migrations apply torre3_ask --remote
migrate-local:
	$(WR) d1 migrations apply torre3 --local
	$(WR) d1 migrations apply torre3_ask --local
seed-local: migrate-local
	$(WR) d1 execute torre3 --local --yes --file ../db/seed.dev.sql
	$(WR) d1 execute torre3 --local --yes --file ../db/rebuild_fts.sql

ingest:
	$(PY) ingest $(ARGS)
validate:
	$(PY) validate
review:
	$(PY) review
review-notes:
	$(PY) review-notes
match:
	$(PY) match
observations:
	$(PY) observations $(ARGS)
ejercicio:
	$(PY) ejercicio $(if $(DESDE),--desde $(DESDE),)
publish:
	$(PY) publish
publish-local:
	$(PY) publish --local

# The monthly routine (PLAN.md §10, Phase 4): put the administrator's new PDFs in data/inbox/
# (kind subfolders or by file name), then run this. It stops before the human steps.
monthly:
	$(PY) ingest $(ARGS)
	$(PY) validate
	$(PY) match
	$(PY) review-notes
	$(PY) observations
	@echo ""
	@echo "Next (human steps):"
	@echo "  1. Transcribe the pages 'ingest' listed as 'to transcribe' (Claude Code), then: make ingest"
	@echo "  2. make review   -> confirm links, payments and actas (127.0.0.1)"
	@echo "  3. Log findings in data/work/observations.json; make observations ARGS=--draft for the administrator"
	@echo "  4. After August: make ejercicio when the yearly balance arrives"
	@echo "  5. After INDEC publishes the month's IPC (~13th): make ipc (Informe para la asamblea)"
	@echo "  6. make publish-local, check with make dev; then make publish and make backup"

build:
	cd web && pnpm build
dev: build
	cd web && pnpm exec wrangler dev --port 8788
deploy: build
	$(WR) deploy

new-link:
	$(PY) link new --kind shared $(LOCALFLAG)
rotate-link:
	$(PY) link rotate $(LOCALFLAG)
admin-link:
	$(PY) link new --kind admin $(LOCALFLAG)
unit-link:
	$(PY) link new --kind unit --unit "$(UNIT)" $(LOCALFLAG)
revoke-link:
	$(PY) link revoke $(if $(ID),--id $(ID),--unit "$(UNIT)") $(LOCALFLAG)
list-links:
	$(PY) link list $(LOCALFLAG)

ipc:
	$(PY) ipc

backup:
	mkdir -p data/backups
	$(WR) d1 export torre3 --remote $(foreach t,$(BACKUP_TABLES),--table $(t)) --output ../data/backups/d1-$$(date +%Y%m%d).sql
	@echo "Restore: apply db/migrations, import the dump, then run db/rebuild_fts.sql. Keep data/ backed up too."

# d1 export refuses databases with virtual tables unless they are left out; search_fts is rebuilt from these.
BACKUP_TABLES := documents pages periods expense_lines tickets ticket_items expense_ticket_links tags \
                 entity_tags reglamento_articles actas acta_items acta_expense_links access_codes comments \
                 comment_reports comment_moderation observations obras obra_expense_links

test: test-py test-web
test-py:
	cd pipeline && uv run ruff check . && uv run pytest -q
test-web:
	cd web && pnpm exec tsc -b && pnpm exec vitest run
