-- Outflows of the liquidación's "Fondo de obra / reserva" ledger. They are expense lines
-- (linkable to receipts and payments) but not part of the month's "Total de Gastos".
ALTER TABLE expense_lines ADD COLUMN fondo INTEGER NOT NULL DEFAULT 0;
