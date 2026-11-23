-- Obras (works paid with cuotas extraordinarias or the fondo de obra) for the "Informe para la
-- asamblea" page: what an acta approved vs what was spent and backed. Curated by hand in
-- data/work/extract/actas.json (`obras`, schemas.Obra) and replaced in full by every publish.

CREATE TABLE obras (
  id INTEGER PRIMARY KEY,                    -- ids.obra_id: stable (by name)
  nombre TEXT NOT NULL,
  aprobado REAL,                             -- approved total; NULL when no acta states it
  criterio TEXT,                             -- how `aprobado` was derived, es-AR ("$ 50.000 × 64 unidades × 4 cuotas")
  detalle TEXT,                              -- roles only
  acta_ids_json TEXT NOT NULL DEFAULT '[]',  -- actas that approved or followed it
  observation_ids_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE obra_expense_links (
  obra_id INTEGER NOT NULL REFERENCES obras(id) ON DELETE CASCADE,
  expense_line_id INTEGER NOT NULL,
  PRIMARY KEY (obra_id, expense_line_id)
);
CREATE INDEX obra_expense_links_line ON obra_expense_links(expense_line_id);
