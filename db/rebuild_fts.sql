-- Rebuilds the full-text index from base tables. Run after every publish and
-- after restoring a backup (wrangler d1 export does not include FTS tables).
-- Restricted pages are never indexed.
DELETE FROM search_fts;

INSERT INTO search_fts (entity_type, entity_id, page_id, title, body)
SELECT 'page', p.id, p.id, d.title || ' · página ' || p.page_no, p.text
FROM pages p JOIN documents d ON d.id = p.document_id
WHERE p.restricted = 0 AND length(p.text) > 0;

INSERT INTO search_fts (entity_type, entity_id, page_id, title, body)
SELECT 'article', a.id, json_extract(a.page_ids_json, '$[0]'),
       COALESCE(d.title || ' · ', '') || 'Artículo ' || a.numero || COALESCE(' · ' || a.titulo, ''), a.texto
FROM reglamento_articles a LEFT JOIN documents d ON d.id = a.document_id;

INSERT INTO search_fts (entity_type, entity_id, page_id, title, body)
SELECT 'expense', e.id, e.page_id, e.concepto,
       e.rubro || ' ' || COALESCE(e.subcategoria, '') || ' ' || e.concepto || ' ' || COALESCE(e.detalle, '') || ' ' || COALESCE(e.proveedor, '')
FROM expense_lines e;

INSERT INTO search_fts (entity_type, entity_id, page_id, title, body)
SELECT 'ticket', t.id, t.page_id, COALESCE(t.proveedor, 'Comprobante'),
       COALESCE(t.proveedor, '') || ' ' || COALESCE(t.descripcion, '') || ' ' || COALESCE(t.subcategoria, '') || ' ' ||
       COALESCE((SELECT group_concat(i.descripcion, ' ') FROM ticket_items i WHERE i.ticket_id = t.id), '')
FROM tickets t
WHERE t.page_id IS NULL OR t.page_id IN (SELECT id FROM pages WHERE restricted = 0);

INSERT INTO search_fts (entity_type, entity_id, page_id, title, body)
SELECT 'acta', a.id, json_extract(a.page_ids_json, '$[0]'),
       CASE WHEN a.numero IS NULL THEN 'Acta' ELSE 'Acta ' || a.numero END || ' · ' || a.fecha,
       a.resumen || ' ' || COALESCE((SELECT group_concat(i.texto, ' ') FROM acta_items i WHERE i.acta_id = a.id), '')
FROM actas a;
