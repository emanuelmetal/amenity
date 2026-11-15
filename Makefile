# Torre 3 portal. See CLAUDE.md. LOCAL=1 targets local wrangler state.
.PHONY: setup migrate migrate-local seed-local ingest validate publish publish-local build dev deploy \
        new-link rotate-link admin-link unit-link revoke-link list-links backup test test-py test-web

PY := cd pipeline && uv run alas3
LOCALFLAG := $(if $(LOCAL),--local,)
WR := cd web && pnpm exec wrangler

setup:
	cd pipeline && uv sync
	cd web && pnpm install
	test -f web/.dev.vars || echo "SESSION_SECRET=$$(openssl rand -hex 32)" > web/.dev.vars

migrate:
	$(WR) d1 migrations apply torre3 --remote
migrate-local:
	$(WR) d1 migrations apply torre3 --local
seed-local: migrate-local
	$(WR) d1 execute torre3 --local --yes --file ../db/seed.dev.sql
	$(WR) d1 execute torre3 --local --yes --file ../db/rebuild_fts.sql

ingest:
	$(PY) ingest $(ARGS)
validate:
	$(PY) validate
publish:
	$(PY) publish
publish-local:
	$(PY) publish --local

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

backup:
	mkdir -p data/backups
	$(WR) d1 export torre3 --remote $(foreach t,$(BACKUP_TABLES),--table $(t)) --output ../data/backups/d1-$$(date +%Y%m%d).sql
	@echo "Restore: apply db/migrations, import the dump, then run db/rebuild_fts.sql. Keep data/ backed up too."

# d1 export refuses databases with virtual tables unless they are left out; search_fts is rebuilt from these.
BACKUP_TABLES := documents pages periods expense_lines tickets ticket_items expense_ticket_links tags \
                 entity_tags reglamento_articles actas acta_items access_codes comments

test: test-py test-web
test-py:
	cd pipeline && uv run ruff check . && uv run pytest -q
test-web:
	cd web && pnpm exec tsc -b && pnpm exec vitest run
