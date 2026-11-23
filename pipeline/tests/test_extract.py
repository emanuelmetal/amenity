from alas3 import liquidacion
from alas3.classify import classify_text
from alas3.extract import parse_reglamento
from alas3.ids import expense_line_ids
from alas3.schemas import Liquidacion, LiquidacionLine, RubroTotal
from alas3.validate import check_fondo, check_liquidacion, check_resumen


def test_reglamento_articles_split_across_pages():
    pages = [
        (
            1,
            "REGLAMENTO DE COPROPIEDAD\nARTÍCULO 1°.- DEL OBJETO. El presente regla-\nmento rige el edificio.\n3",
        ),
        (
            2,
            "ARTICULO 2: Las mascotas se permiten\nsiempre que no molesten.\nArtículo 3 - DE LAS COCHERAS. Uso exclusivo",
        ),
        (3, "de los propietarios.\nARTICULO PRIMERO BIS: texto"),
    ]
    reg = parse_reglamento(pages)
    nums = [a.numero for a in reg.articles]
    assert nums == ["1", "2", "3", "PRIMERO"]
    a1, a2, a3, _ = reg.articles
    assert a1.titulo == "Del objeto"
    assert a1.texto == "El presente reglamento rige el edificio."  # hyphenation joined, page number dropped
    assert a1.page_nos == [1]
    assert "siempre que no molesten" in a2.texto
    assert a3.titulo == "De las cocheras"
    assert a3.page_nos == [2, 3]
    assert [a.orden for a in reg.articles] == [1, 2, 3, 4]


def test_liquidacion_summary_block_before_detail_is_ignored():
    # Since 07/2026 the page opens with an upper-case header and an income summary
    # before "DETALLE DE LOS GASTOS"; none of it may become an expense line.
    text = "\n".join(
        [
            "EDIFICIO DE PRUEBA, ADMINISTRACION DE CONSORCIOS",
            "Concepto Ingreso / Egreso  Ingreso  Egreso",
            "Saldo Inicial del Período 10/2026  5.000.000,00",
            "EXPENSAS COMUNES  4.000.000,00",
            "Total de Gastos del Mes  1.100.000,00",
            "Saldo Final del Período 10/2026  7.900.000,00",
            "DETALLE DE LOS GASTOS AL MES: OCTUBRE DE 2026",
            "Concepto Gastos  Detalle Gastos  Gastos",
            "SUELDOS Y JORNALES",
            "SUELDO ENCARGADO  mes 10/2026  1,000,000.00",
            "SERVICIOS Y SERVICES",
            "SERVICIO DE JARDINERIA  mes 10/2026  100,000.00",
            "Total de Gastos del Período: 10/2026  1,100,000.00",
        ]
    )
    liq = liquidacion.parse("2026-10", [(1, text)])
    assert [ln.concepto for ln in liq.lines] == ["SUELDO ENCARGADO", "SERVICIO DE JARDINERIA"]
    assert liq.total == 1_100_000.0
    assert check_liquidacion(liq) == []


def test_liquidacion_parser_and_validation():
    text = "\n".join(
        [
            "EDIFICIO ALAS 3  -  TORRE 3",
            "RUBRO 1 - SUELDOS Y CARGAS SOCIALES",
            "Sueldo encargado  1.500.000,00",
            "TOTAL RUBRO 1  1.500.000,00",
            "RUBRO 2 - MANTENIMIENTO",
            "Pintura palier  Pinturas SA 30-71234567-9  250.000,50",
            "Reintegro taxis encargado  12.000,00",
            "TOTAL RUBRO 2  262.000,50",
            "TOTAL GASTOS DEL MES  1.762.000,50",
        ]
    )
    liq = liquidacion.parse("2026-10", [(1, text)])
    assert liq.total == 1_762_000.50
    assert [rt.total for rt in liq.rubro_totals] == [1_500_000.0, 262_000.50]
    assert len(liq.lines) == 3
    pint = liq.lines[1]
    assert pint.rubro == "2. Mantenimiento"
    assert liq.lines[0].rubro == "1. Sueldos y cargas sociales"
    assert pint.concepto == "Pintura palier"
    assert pint.cuit == "30-71234567-9"
    assert pint.importe == 250_000.50
    assert all(not ln.verified and ln.confidence < 1 for ln in liq.lines)
    assert check_liquidacion(liq) == []


def test_validation_reports_mismatches():
    liq = Liquidacion(
        period="2026-10",
        total=100.0,
        rubro_totals=[RubroTotal(rubro="A", total=60.0)],
        lines=[
            LiquidacionLine(rubro="A", concepto="x", importe=50.0),
            LiquidacionLine(rubro="B", concepto="y", importe=40.0),
        ],
    )
    problems = check_liquidacion(liq)
    assert any("A: lines sum 50.00 != rubro total 60.00" in p for p in problems)
    assert any("without a total" in p for p in problems)
    assert any("!= liquidación total" in p for p in problems)


def test_parse_amount_formats():
    assert liquidacion.parse_amount("1.234,56") == 1234.56
    assert liquidacion.parse_amount("$ 12,00") == 12.0
    assert liquidacion.parse_amount("(1.000,00)") == -1000.0


def test_classify_whole_words():
    assert classify_text("Reintegro taxi encargado")[0] == "Movilidad / taxi"
    assert classify_text("Reintegro taxis encargado")[0] == "Movilidad / taxi"
    assert classify_text("Gastos bancarios varios")[0] != "Gas"
    assert classify_text("MetroGas factura")[0] == "Gas"
    assert classify_text("Ascensores Sur SRL")[0] == "Ascensor"


SUMMARY = [
    "Concepto Ingreso / Egreso  Ingreso  Egreso",
    "Saldo Inicial del Período 10/2026  1.000.000,00",
    "EXPENSAS COMUNES  2.000.000,00",
    "PUNITORIOS MENSUALES  50.000,00",
    "pasado a fondo de obra  300.000,00",
    "Total de Gastos del Mes  1.100.000,00",
    "Saldo Final del Período 10/2026  1.650.000,00",
    "INGRESOS PERÍODO: 2.050.000,00  EGRESOS PERÍODO: 1.400.000,00  SALDO DEL PERÍODO: 650.000,00",
    "DETALLE DE LOS GASTOS AL MES: OCTUBRE DE 2026",
    "SUELDOS Y JORNALES",
    "SUELDO ENCARGADO  mes 10/2026  1,100,000.00",
    "Total de Gastos del Período: 10/2026  1,100,000.00",
]


def test_resumen_parsed_and_outflows_found_from_period_totals():
    liq = liquidacion.parse("2026-10", [(1, "\n".join(SUMMARY))])
    r = liq.resumen
    assert (r.saldo_inicial, r.saldo_final, r.ingresos, r.egresos) == (
        1_000_000,
        1_650_000,
        2_050_000,
        1_400_000,
    )
    assert [(i.concepto, i.tipo) for i in r.items] == [
        ("EXPENSAS COMUNES", "ingreso"),
        ("PUNITORIOS MENSUALES", "ingreso"),
        ("pasado a fondo de obra", "egreso"),  # the column is lost in text; the totals tell
    ]
    assert check_liquidacion(liq) == [] and check_resumen(liq) == []


def test_resumen_balance_mismatch_is_reported():
    bad = [ln.replace("1.650.000,00", "1.600.000,00") for ln in SUMMARY]
    liq = liquidacion.parse("2026-10", [(1, "\n".join(bad))])
    assert any("saldo final" in p for p in check_resumen(liq))


FONDO_P1 = """DETALLE DE LOS GASTOS AL MES: DICIEMBRE DE 2025
Concepto Gastos  Detalle Gastos  Gastos
REPARACIONES Y TRABAJOS VS.
MANO DE OBRA TRABAJO DE  Pintura  1,000.00
Total de Gastos del Período: 12/2025  1,000.00
FONDO DE RESERVA  INGRESOS  EGRESOS
SALDO INICIAL 'FONDO DE RESERVA' AL 12/2025  10.000,00
345 CTA INVERSION OBRA EXPLANADA  500,00
ingreso de fondo corriente para obra  2.000,00"""
FONDO_P2 = """ADMINISTRACIÓN DE CONSORCIOS  Complejo Edilicio
168 MANO DE OBRA TRABAJO DE (cuota 5 obra explanada)  7.000,00
503 APORTES ADMINISTRACION CENTRAL (obra explanada)  1.500,00
Obra cochera  300,00
SALDO FINAL 'FONDO DE RESERVA' AL 12/2025  3.700,00
TOTAL EXPENSAS PRORRATEADAS:  $ 1.000,00"""


def test_fondo_outflows_become_fund_lines_outside_the_month_total():
    liq = liquidacion.parse("2025-12", [(1, FONDO_P1), (2, FONDO_P2)])
    fondo = [ln for ln in liq.lines if ln.fondo]
    # 10.000 + 2.500 in - 8.800 out = 3.700: the split comes from the balance.
    assert [(ln.concepto, ln.detalle, ln.importe, ln.page_no) for ln in fondo] == [
        ("MANO DE OBRA TRABAJO DE", "cuota 5 obra explanada", 7000.0, 2),
        ("APORTES ADMINISTRACION CENTRAL", "obra explanada", 1500.0, 2),
        ("Obra cochera", None, 300.0, 2),
    ]
    assert {ln.rubro for ln in fondo} == {liquidacion.FONDO_RUBRO}
    assert [i.tipo for i in liq.fondo.items] == ["ingreso", "ingreso", "egreso", "egreso", "egreso"]
    assert check_liquidacion(liq) == [] and check_fondo(liq) == []  # total = ordinary lines only
    # Ordinary lines keep their ids; fund lines live in their own id namespace.
    plain = liquidacion.parse("2025-12", [(1, FONDO_P1.split("FONDO DE RESERVA")[0])])
    assert expense_line_ids(liq)[0] == expense_line_ids(plain)[0]
    assert len(set(expense_line_ids(liq))) == len(liq.lines)


def test_fondo_unbalanced_is_reported():
    liq = liquidacion.parse("2025-12", [(1, FONDO_P1), (2, FONDO_P2.replace("3.700,00", "3.000,00"))])
    assert not [ln for ln in liq.lines if ln.fondo]
    assert check_fondo(liq)
