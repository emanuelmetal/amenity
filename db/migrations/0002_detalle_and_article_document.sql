-- Liquidación lines carry a "Detalle" column next to the concepto.
ALTER TABLE expense_lines ADD COLUMN detalle TEXT;

-- Several reglamento documents can coexist (Reglamento Interno, Reglamento de Copropiedad).
ALTER TABLE reglamento_articles ADD COLUMN document_id INTEGER REFERENCES documents(id);
CREATE INDEX idx_articles_document ON reglamento_articles(document_id, orden);
