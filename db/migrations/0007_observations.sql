-- The auditor's observations about the administration's accounts (pipeline/alas3/observations.py).
-- Source of truth: data/work/observations.json; publish replaces the whole table every time.
CREATE TABLE observations (
  id TEXT PRIMARY KEY,                     -- "<period>-<nn>"
  period_id TEXT NOT NULL,                 -- the month it is about
  tipo TEXT NOT NULL,
  titulo TEXT NOT NULL,
  detalle TEXT NOT NULL,
  importe REAL,                            -- amount at stake
  estado TEXT NOT NULL CHECK (estado IN ('abierta','enviada','respondida','resuelta','descartada')),
  fecha TEXT NOT NULL,                     -- when it was raised
  respuesta TEXT,
  fecha_respuesta TEXT,
  line_ids_json TEXT NOT NULL DEFAULT '[]',
  ticket_ids_json TEXT NOT NULL DEFAULT '[]',
  movement_ids_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_observations_period ON observations(period_id);
