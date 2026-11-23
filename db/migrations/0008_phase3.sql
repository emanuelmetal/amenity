-- Phase 3: actas (minutes book, transcribed from photos) and anonymous comments.

-- The Phase 1 placeholders were never filled: recreate them with what the book gives.
DROP TABLE IF EXISTS acta_items;
DROP TABLE IF EXISTS actas;

CREATE TABLE actas (
  id INTEGER PRIMARY KEY,               -- ids.acta_id: stable across publishes
  numero INTEGER,                       -- "Acta 101"
  fecha TEXT NOT NULL,                  -- YYYY-MM-DD
  tipo TEXT NOT NULL CHECK (tipo IN ('comision','asamblea','otro')),
  resumen TEXT NOT NULL,                -- people by role only
  asistentes_json TEXT NOT NULL DEFAULT '[]',
  page_ids_json TEXT NOT NULL DEFAULT '[]',  -- published folios, in reading order
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE acta_items (
  id INTEGER PRIMARY KEY,               -- ids.acta_item_ids
  acta_id INTEGER NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
  orden INTEGER NOT NULL,
  tipo TEXT NOT NULL CHECK (tipo IN ('decision','tarea','tema')),
  texto TEXT NOT NULL,
  importe REAL,
  period_id TEXT,                       -- month it is about, when it names one
  observation_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX acta_items_acta ON acta_items(acta_id, orden);

-- Gasto <-> decision: both directions are shown (acta detail, expense side panel).
CREATE TABLE acta_expense_links (
  acta_item_id INTEGER NOT NULL REFERENCES acta_items(id) ON DELETE CASCADE,
  expense_line_id INTEGER NOT NULL,
  PRIMARY KEY (acta_item_id, expense_line_id)
);
CREATE INDEX acta_expense_links_line ON acta_expense_links(expense_line_id);

-- Comments (PLAN.md §7). Written by the site, never by the pipeline.
-- moderated = 1 once a moderator acted on it: reports no longer auto-hide it.
ALTER TABLE comments ADD COLUMN moderated INTEGER NOT NULL DEFAULT 0;
CREATE INDEX comments_entity ON comments(entity_type, entity_id, status, created_at);
CREATE INDEX comments_author ON comments(author_key, created_at);
CREATE INDEX comments_recent ON comments(status, created_at);

-- One report per device and comment (author_key = HMAC of the reporter's device).
CREATE TABLE comment_reports (
  comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
  author_key TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (comment_id, author_key)
);

-- Who (which admin access code) hid or restored what, and when.
CREATE TABLE comment_moderation (
  id INTEGER PRIMARY KEY,
  comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('hide','restore')),
  access_code_id INTEGER REFERENCES access_codes(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX comment_moderation_comment ON comment_moderation(comment_id, created_at);
