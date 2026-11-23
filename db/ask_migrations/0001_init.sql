-- The "Preguntale al portal" database (D1 `torre3_ask`, binding ASK_DB). It holds ONLY the
-- data the ask_* views of the main database expose (db/migrations/0009_ask.sql), copied as
-- plain tables at the end of every publish (pipeline/alas3/ask_sync.py). The LLM-written SQL
-- of web/server/ask.ts runs here and nowhere else: even a gap in guardSql cannot reach
-- comments, access codes or anything private, and a slow query cannot stall the main site.
-- Never add a table here that the ask_* views do not define; columns must match them
-- (web/test/ask.test.ts checks it).

CREATE TABLE ask_meses (mes TEXT PRIMARY KEY, anio INTEGER, total_gastos REAL, ingresos REAL, egresos REAL, saldo_inicial REAL, saldo_final REAL);

CREATE TABLE ask_gastos (
  id INTEGER PRIMARY KEY, mes TEXT, anio INTEGER, rubro TEXT, subcategoria TEXT, concepto TEXT, detalle TEXT,
  proveedor TEXT, importe REAL, fondo_reserva INTEGER, verificado INTEGER, con_comprobante INTEGER, con_pago INTEGER,
  hay_comprobantes_del_mes INTEGER, hay_resumen_bancario_del_mes INTEGER, respaldado INTEGER
);
CREATE INDEX ask_gastos_mes ON ask_gastos(mes);

CREATE TABLE ask_comprobantes (
  id INTEGER PRIMARY KEY, mes TEXT, fecha TEXT, tipo TEXT, letra TEXT, proveedor TEXT, descripcion TEXT,
  total REAL, subcategoria TEXT, verificado INTEGER, etiquetas TEXT
);
CREATE INDEX ask_comprobantes_mes ON ask_comprobantes(mes);

CREATE TABLE ask_gasto_comprobante (gasto_id INTEGER, comprobante_id INTEGER, estado TEXT, PRIMARY KEY (gasto_id, comprobante_id));
CREATE INDEX ask_gasto_comprobante_c ON ask_gasto_comprobante(comprobante_id);

CREATE TABLE ask_movimientos (id INTEGER PRIMARY KEY, mes TEXT, fecha TEXT, banco TEXT, descripcion TEXT, importe REAL, tipo TEXT, cheque_numero TEXT);
CREATE INDEX ask_movimientos_mes ON ask_movimientos(mes);

CREATE TABLE ask_gasto_pago (gasto_id INTEGER, movimiento_id INTEGER, estado TEXT, PRIMARY KEY (gasto_id, movimiento_id));
CREATE INDEX ask_gasto_pago_m ON ask_gasto_pago(movimiento_id);

CREATE TABLE ask_observaciones (
  id TEXT PRIMARY KEY, mes TEXT, tipo TEXT, titulo TEXT, detalle TEXT, importe REAL, estado TEXT, fecha TEXT,
  respuesta TEXT, fecha_respuesta TEXT
);

CREATE TABLE ask_actas (id INTEGER PRIMARY KEY, numero INTEGER, fecha TEXT, tipo TEXT, resumen TEXT, verificada INTEGER);

CREATE TABLE ask_acta_items (id INTEGER PRIMARY KEY, acta_id INTEGER, orden INTEGER, tipo TEXT, texto TEXT, importe REAL, mes TEXT);
CREATE INDEX ask_acta_items_acta ON ask_acta_items(acta_id);

CREATE TABLE ask_articulos (id INTEGER PRIMARY KEY, numero TEXT, orden INTEGER, titulo TEXT, texto TEXT);
