-- Phase 2: receipts (tickets), matching, income summary per period.

-- Account summary of each liquidación ("Resumen de cuenta").
ALTER TABLE periods ADD COLUMN saldo_inicial REAL;
ALTER TABLE periods ADD COLUMN saldo_final REAL;
ALTER TABLE periods ADD COLUMN ingresos REAL;
ALTER TABLE periods ADD COLUMN egresos REAL;
ALTER TABLE periods ADD COLUMN resumen_json TEXT NOT NULL DEFAULT '[]';  -- [{concepto, importe, tipo}]

-- A receipt can span several pages (copies, multi-page invoices) and several
-- receipts can share one page (overlapping photos), so pages are a list.
ALTER TABLE tickets ADD COLUMN document_id INTEGER REFERENCES documents(id);
ALTER TABLE tickets ADD COLUMN page_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE tickets ADD COLUMN kind TEXT NOT NULL DEFAULT 'otro';  -- factura|recibo|presupuesto|ticket|servicio|otro
ALTER TABLE tickets ADD COLUMN letra TEXT;
ALTER TABLE tickets ADD COLUMN cae TEXT;
ALTER TABLE tickets ADD COLUMN descripcion TEXT;
ALTER TABLE tickets ADD COLUMN period_id TEXT;
ALTER TABLE tickets ADD COLUMN subcategoria TEXT;
CREATE INDEX idx_tickets_period ON tickets(period_id);
CREATE INDEX idx_tickets_document ON tickets(document_id);
CREATE INDEX idx_links_ticket ON expense_ticket_links(ticket_id);
CREATE INDEX idx_entity_tags ON entity_tags(tag_id, entity_type);
