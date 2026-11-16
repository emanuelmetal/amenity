-- FAKE data for local development only (`make seed-local`). Not real building data.
-- Page images are not seeded, so the viewer shows a broken image until `make publish-local`.
DELETE FROM expense_payment_links; DELETE FROM bank_movements; DELETE FROM expense_lines; DELETE FROM periods; DELETE FROM reglamento_articles; DELETE FROM pages; DELETE FROM documents;

INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages) VALUES
  (901, 'reglamento', NULL, 'Reglamento de copropiedad (EJEMPLO)', 'dev/reglamento.pdf', 'dev-901', 2),
  (902, 'liquidacion', '2026-09', 'Liquidación de expensas 2026-09 (EJEMPLO)', 'dev/l09.pdf', 'dev-902', 1),
  (903, 'liquidacion', '2026-10', 'Liquidación de expensas 2026-10 (EJEMPLO)', 'dev/l10.pdf', 'dev-903', 1);

INSERT INTO pages (id, document_id, page_no, r2_key_img, text, ocr_engine) VALUES
  (9010001, 901, 1, 'dev/901-1.webp', 'ARTÍCULO 1. DEL OBJETO. Texto de ejemplo del reglamento sobre cocheras y espacios comunes.', 'pdf-text'),
  (9010002, 901, 2, 'dev/901-2.webp', 'ARTÍCULO 2. MASCOTAS. Texto de ejemplo sobre mascotas en el edificio.', 'pdf-text'),
  (9020001, 902, 1, 'dev/902-1.webp', 'Liquidación de ejemplo septiembre', 'pdf-text'),
  (9030001, 903, 1, 'dev/903-1.webp', 'Liquidación de ejemplo octubre', 'pdf-text');

INSERT INTO periods (id, total, document_id) VALUES ('2026-09', 2310000, 902), ('2026-10', 2450000, 903);

INSERT INTO expense_lines (period_id, rubro, subcategoria, concepto, proveedor, importe, page_id, confidence, verified) VALUES
  ('2026-09', '1. Sueldos y cargas sociales', 'Sueldos encargado', 'Sueldo encargado (ejemplo)', NULL, 1500000, 9020001, 0.7, 1),
  ('2026-09', '2. Servicios públicos', 'Electricidad', 'Electricidad espacios comunes', 'Proveedor Luz (ejemplo)', 310000, 9020001, 0.7, 0),
  ('2026-09', '3. Mantenimiento', 'Ascensor', 'Abono mensual ascensores', 'Ascensores Ejemplo SRL', 500000, 9020001, 0.7, 0),
  ('2026-10', '1. Sueldos y cargas sociales', 'Sueldos encargado', 'Sueldo encargado (ejemplo)', NULL, 1500000, 9030001, 0.7, 1),
  ('2026-10', '2. Servicios públicos', 'Electricidad', 'Electricidad espacios comunes', 'Proveedor Luz (ejemplo)', 320000, 9030001, 0.7, 0),
  ('2026-10', '3. Mantenimiento', 'Pintura', 'Pintura palier piso 4', 'Pinturería Ejemplo', 450000, 9030001, 0.7, 0),
  ('2026-10', '3. Mantenimiento', 'Movilidad / taxi', 'Reintegro taxis encargado', NULL, 180000, 9030001, 0.7, 0);

INSERT INTO reglamento_articles (numero, orden, titulo, texto, page_ids_json) VALUES
  ('1', 1, 'Del objeto', 'Texto de ejemplo del reglamento sobre cocheras y espacios comunes.', '[9010001]'),
  ('2', 2, 'Mascotas', 'Texto de ejemplo sobre mascotas en el edificio.', '[9010002]');

-- Bank payments (FAKE): one transfer and the month's grouped bank charges.
INSERT INTO bank_movements (id, document_id, page_id, page_ids_json, period_id, fecha, banco, descripcion, importe, kind, items_json) VALUES
  (9500001, 903, 9030001, '[9030001]', '2026-10', '2026-10-15', 'Banco Ejemplo S.A.', 'TRANSF.INTERB.DISTINTO TIT. PINTURERIA EJEMPLO', 450000, 'debito', '[]'),
  (9500002, 903, 9030001, '[9030001]', '2026-10', '2026-10-31', 'Banco Ejemplo S.A.', 'Gastos bancarios oct 2026 (comisiones e impuestos)', 12500, 'gastos',
   '[{"descripcion":"IMPUESTO LEY 25413","importe":9000,"cantidad":12},{"descripcion":"I.V.A.","importe":3500,"cantidad":5}]');
INSERT INTO expense_payment_links (expense_line_id, movement_id, score, status)
  SELECT id, 9500001, 0.9, 'auto' FROM expense_lines WHERE period_id = '2026-10' AND concepto = 'Pintura palier piso 4';
