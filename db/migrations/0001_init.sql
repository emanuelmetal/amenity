-- Torre 3 portal: initial schema (PLAN.md §5). All phases' tables are created now.

CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('liquidacion','comprobantes','reglamento','acta','otro')),
  period TEXT,                       -- 'YYYY-MM' when applicable
  title TEXT NOT NULL,
  r2_key_pdf TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  pages INTEGER NOT NULL,
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE pages (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_no INTEGER NOT NULL,          -- 1-based
  r2_key_img TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  ocr_engine TEXT NOT NULL DEFAULT 'none',  -- 'pdf-text' | 'tesseract' | 'paddle' | 'none'
  has_qr INTEGER NOT NULL DEFAULT 0,
  restricted INTEGER NOT NULL DEFAULT 0,    -- 1 = never served, never indexed
  UNIQUE (document_id, page_no)
);

CREATE TABLE periods (
  id TEXT PRIMARY KEY,               -- 'YYYY-MM'
  total REAL,
  document_id INTEGER REFERENCES documents(id)
);

CREATE TABLE expense_lines (
  id INTEGER PRIMARY KEY,
  period_id TEXT NOT NULL REFERENCES periods(id),
  rubro TEXT NOT NULL,
  subcategoria TEXT,
  concepto TEXT NOT NULL,
  proveedor TEXT,
  cuit TEXT,
  importe REAL NOT NULL,
  page_id INTEGER REFERENCES pages(id),
  confidence REAL NOT NULL DEFAULT 1.0,
  verified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_expense_period_rubro ON expense_lines(period_id, rubro);

CREATE TABLE tickets (
  id INTEGER PRIMARY KEY,
  page_id INTEGER REFERENCES pages(id),
  fecha TEXT,
  proveedor TEXT,
  cuit TEXT,
  tipo_cmp INTEGER,
  pto_vta INTEGER,
  nro_cmp INTEGER,
  total REAL,
  medio_pago TEXT,
  source TEXT NOT NULL CHECK (source IN ('qr','llm','manual')),
  confidence REAL NOT NULL DEFAULT 1.0,
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE ticket_items (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  descripcion TEXT NOT NULL,
  cantidad REAL,
  importe REAL
);

CREATE TABLE expense_ticket_links (
  expense_line_id INTEGER NOT NULL REFERENCES expense_lines(id) ON DELETE CASCADE,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('auto','verified','rejected')),
  PRIMARY KEY (expense_line_id, ticket_id)
);

CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE entity_tags (
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (entity_type, entity_id, tag_id)
);

CREATE TABLE reglamento_articles (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL,
  orden INTEGER NOT NULL,            -- display order
  titulo TEXT,
  texto TEXT NOT NULL,
  page_ids_json TEXT NOT NULL DEFAULT '[]',
  verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE actas (
  id INTEGER PRIMARY KEY,
  fecha TEXT NOT NULL,
  resumen TEXT,
  document_id INTEGER REFERENCES documents(id)
);

CREATE TABLE acta_items (
  id INTEGER PRIMARY KEY,
  acta_id INTEGER NOT NULL REFERENCES actas(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('decision','tarea','tema')),
  texto TEXT NOT NULL,
  importe REAL,
  related_expense_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE access_codes (
  id INTEGER PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,    -- hex sha256 of the token; the token itself is never stored
  kind TEXT NOT NULL CHECK (kind IN ('shared','unit','admin')),
  unit_label TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at TEXT,
  last_used_at TEXT,
  uses INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE access_attempts (
  ip_hash TEXT NOT NULL,
  window_start INTEGER NOT NULL,     -- unix seconds, start of the hour bucket
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (ip_hash, window_start)
);

CREATE TABLE comments (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id INTEGER,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  author_key TEXT NOT NULL,
  access_code_id INTEGER REFERENCES access_codes(id),
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden','removed')),
  reports INTEGER NOT NULL DEFAULT 0
);

-- Full-text search across pages, articles, acta items and expense conceptos.
-- Rebuilt by the pipeline's publish step (not exported by `wrangler d1 export`).
CREATE VIRTUAL TABLE search_fts USING fts5(
  entity_type UNINDEXED,
  entity_id UNINDEXED,
  page_id UNINDEXED,
  title,
  body,
  tokenize = 'unicode61 remove_diacritics 2'
);
