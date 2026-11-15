from alas3 import liquidacion
from alas3.classify import classify_text
from alas3.extract import parse_reglamento
from alas3.schemas import Liquidacion, LiquidacionLine, RubroTotal
from alas3.validate import check_liquidacion


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
