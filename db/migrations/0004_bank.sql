-- Bank statements attached to the receipts: debits are evidence that an expense was
-- paid. Credits (owners' expensas payments) are never stored one by one.
CREATE TABLE bank_movements (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  page_id INTEGER REFERENCES pages(id),
  page_ids_json TEXT NOT NULL DEFAULT '[]',
  period_id TEXT NOT NULL,                 -- month of the movement
  fecha TEXT NOT NULL,
  banco TEXT,
  comprobante TEXT,
  codigo TEXT,
  descripcion TEXT NOT NULL,
  importe REAL NOT NULL,                   -- positive: money that left the account
  kind TEXT NOT NULL CHECK (kind IN ('debito','gastos')),
  items_json TEXT NOT NULL DEFAULT '[]'    -- gastos: [{descripcion, importe, cantidad}]
);
CREATE INDEX idx_bank_movements_period ON bank_movements(period_id);

CREATE TABLE expense_payment_links (
  expense_line_id INTEGER NOT NULL REFERENCES expense_lines(id) ON DELETE CASCADE,
  movement_id INTEGER NOT NULL REFERENCES bank_movements(id) ON DELETE CASCADE,
  score REAL NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('auto','verified','rejected')),
  PRIMARY KEY (expense_line_id, movement_id)
);
CREATE INDEX idx_payment_links_movement ON expense_payment_links(movement_id);
