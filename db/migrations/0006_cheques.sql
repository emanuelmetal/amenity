-- Cheques the consortium issued are payment evidence too (pipeline/alas3/payments.py):
-- a cleared cheque is attached to its bank debit (cheque_* columns, photo in page_ids_json);
-- one no statement shows cleared yet is a movement of its own, kind 'cheque'.
-- SQLite cannot change a CHECK constraint: rebuild the table (publish refills it anyway).
PRAGMA defer_foreign_keys = true;
CREATE TABLE bank_movements_new (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  page_id INTEGER REFERENCES pages(id),
  page_ids_json TEXT NOT NULL DEFAULT '[]',
  period_id TEXT NOT NULL,                 -- month of the movement (a pending cheque: its payment date)
  fecha TEXT NOT NULL,
  banco TEXT,
  comprobante TEXT,
  codigo TEXT,
  descripcion TEXT NOT NULL,
  importe REAL NOT NULL,                   -- positive: money that left (or will leave) the account
  kind TEXT NOT NULL CHECK (kind IN ('debito','gastos','cheque')),
  items_json TEXT NOT NULL DEFAULT '[]',   -- gastos: [{descripcion, importe, cantidad}]
  cheque_numero TEXT,
  cheque_fecha_pago TEXT
);
INSERT INTO bank_movements_new (id, document_id, page_id, page_ids_json, period_id, fecha, banco, comprobante, codigo,
                                descripcion, importe, kind, items_json)
  SELECT id, document_id, page_id, page_ids_json, period_id, fecha, banco, comprobante, codigo,
         descripcion, importe, kind, items_json FROM bank_movements;
DROP TABLE bank_movements;
ALTER TABLE bank_movements_new RENAME TO bank_movements;
CREATE INDEX idx_bank_movements_period ON bank_movements(period_id);
