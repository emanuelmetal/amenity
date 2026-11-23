-- Phase 4, "Preguntale al portal": natural-language question -> SQL written by an LLM.
-- The generated SQL may only read these ask_* views (web/server/ask.ts enforces it token by
-- token). They expose what the site already shows, minus anything not needed to answer a
-- question: no CUIT/CUIL, no R2 keys, no page text, no comments, no access codes.
-- Column names are Spanish because the model writes Spanish questions into SQL.
-- Keep the coverage logic (con_comprobante / con_pago / respaldado) in sync with
-- HAS_RECEIPT / HAS_PAYMENT / BACKED in web/server/api.ts (a test compares them).

CREATE VIEW ask_meses AS
SELECT p.id AS mes, CAST(substr(p.id, 1, 4) AS INTEGER) AS anio, p.total AS total_gastos,
       p.ingresos, p.egresos, p.saldo_inicial, p.saldo_final
FROM periods p;

-- Base of ask_gastos (not offered to the model).
CREATE VIEW ask_gastos_base AS
SELECT e.id, e.period_id AS mes, CAST(substr(e.period_id, 1, 4) AS INTEGER) AS anio,
       e.rubro, e.subcategoria, e.concepto, e.detalle, e.proveedor, e.importe,
       e.fondo AS fondo_reserva, e.verified AS verificado,
       (EXISTS (SELECT 1 FROM expense_ticket_links l WHERE l.expense_line_id = e.id
                  AND (l.status = 'verified' OR (l.status = 'auto' AND l.score >= 0.9)))
        OR EXISTS (SELECT 1 FROM expense_payment_links l JOIN bank_movements b ON b.id = l.movement_id
                   WHERE l.expense_line_id = e.id AND b.kind = 'gastos'
                     AND (l.status = 'verified' OR (l.status = 'auto' AND l.score >= 0.9)))) AS con_comprobante,
       EXISTS (SELECT 1 FROM expense_payment_links l WHERE l.expense_line_id = e.id
                 AND (l.status = 'verified' OR (l.status = 'auto' AND l.score >= 0.9))) AS con_pago,
       (e.period_id IN (SELECT d.period FROM tickets t JOIN documents d ON d.id = t.document_id WHERE d.period IS NOT NULL)
        OR strftime('%Y-%m', e.period_id || '-01', '-1 month')
           IN (SELECT d.period FROM tickets t JOIN documents d ON d.id = t.document_id WHERE d.period IS NOT NULL)) AS hay_comprobantes_del_mes,
       e.period_id IN (SELECT period_id FROM bank_movements WHERE kind != 'cheque') AS hay_resumen_bancario_del_mes
FROM expense_lines e;

-- A gasto is "respaldado" when it has a receipt AND a bank payment, each required only when
-- that kind of evidence was uploaded for its month, and at least one of them (api.ts BACKED).
CREATE VIEW ask_gastos AS
SELECT g.*,
       ((g.con_comprobante OR g.con_pago)
        AND NOT (NOT g.con_comprobante AND g.hay_comprobantes_del_mes)
        AND NOT (NOT g.con_pago AND g.hay_resumen_bancario_del_mes)) AS respaldado
FROM ask_gastos_base g;

CREATE VIEW ask_comprobantes AS
SELECT t.id, t.period_id AS mes, t.fecha, t.kind AS tipo, t.letra, t.proveedor, t.descripcion,
       t.total, t.subcategoria, t.verified AS verificado,
       (SELECT group_concat(g.name, ', ') FROM entity_tags et JOIN tags g ON g.id = et.tag_id
        WHERE et.entity_type = 'ticket' AND et.entity_id = t.id) AS etiquetas
FROM tickets t;

CREATE VIEW ask_gasto_comprobante AS
SELECT l.expense_line_id AS gasto_id, l.ticket_id AS comprobante_id,
       CASE WHEN l.status = 'verified' THEN 'confirmado'
            WHEN l.score >= 0.9 THEN 'automatico' ELSE 'posible' END AS estado
FROM expense_ticket_links l WHERE l.status != 'rejected';

CREATE VIEW ask_movimientos AS
SELECT b.id, b.period_id AS mes, b.fecha, b.banco, b.descripcion, b.importe, b.kind AS tipo,
       b.cheque_numero
FROM bank_movements b;

CREATE VIEW ask_gasto_pago AS
SELECT l.expense_line_id AS gasto_id, l.movement_id AS movimiento_id,
       CASE WHEN l.status = 'verified' THEN 'confirmado'
            WHEN l.score >= 0.9 THEN 'automatico' ELSE 'posible' END AS estado
FROM expense_payment_links l WHERE l.status != 'rejected';

CREATE VIEW ask_observaciones AS
SELECT o.id, o.period_id AS mes, o.tipo, o.titulo, o.detalle, o.importe, o.estado, o.fecha,
       o.respuesta, o.fecha_respuesta
FROM observations o;

CREATE VIEW ask_actas AS
SELECT a.id, a.numero, a.fecha, a.tipo, a.resumen, a.verified AS verificada FROM actas a;

CREATE VIEW ask_acta_items AS
SELECT i.id, i.acta_id, i.orden, i.tipo, i.texto, i.importe, i.period_id AS mes FROM acta_items i;

CREATE VIEW ask_articulos AS
SELECT r.id, r.numero, r.orden, r.titulo, r.texto FROM reglamento_articles r;

-- Daily question counters (rate limit and the global cap that keeps Workers AI in its free
-- allocation). `key` is an HMAC of the device id, or '*' for the global count. The questions
-- themselves are never stored.
CREATE TABLE ask_usage (
  day TEXT NOT NULL,
  key TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, key)
);
