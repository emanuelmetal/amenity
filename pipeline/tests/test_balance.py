"""The administrator's yearly balance and the ejercicio. Invented data only."""

from types import SimpleNamespace

import pymupdf

from alas3.balance import Balance, Fund, Rubro, arithmetic, continuity, parse_balance, reconcile
from alas3.config import ejercicio
from alas3.match import LineRef, TicketRef, match


def _pdf(path, rows):
    """rows: (y, text, x_left) or (y, amount, x_right): amounts right-aligned like the real one."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for y, s, x in rows:
        if isinstance(s, str):
            page.insert_text((x, y), s, fontsize=7)
        else:
            text = f"{s:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            page.insert_text((x - pymupdf.get_text_length(text, fontsize=7), y), text, fontsize=7)
    doc.save(path)
    return path


def test_parses_sections_columns_and_continuation_lines(tmp_path):
    p = _pdf(tmp_path / "b.pdf", [
        (40, "RESUMEN DE CUENTA ENTRE LOS PERÍODOS 09/2025 Y EL 08/2026", 140),
        (52, "Concepto Ingreso / Egreso", 120), (52, "Ingreso", 440), (52, "Egreso", 540),
        (64, "Saldo Inicial al Período 09/2025", 21), (64, 100.0, 470),
        (76, "EXPENSAS COMUNES", 21), (76, 1000.0, 470),
        (88, "pasado a fondo de obra", 21), (88, 50.0, 580),
        (100, "Total de Gastos", 21), (100, 900.0, 580),
        (112, "Saldo Final al Período 08/2026", 21), (112, 150.0, 580),
        (124, "DETALLE DE LOS GASTOS ENTRE LOS PERÍODOS 09/2025 Y EL 08/2026", 135),
        (136, "Concepto Gastos Detalle Gastos Gtos.A Gtos.B Gtos.C Tot.Rubro % Inc.", 52),
        (148, "SERVICIOS", 22), (148, 900.0, 540), (148, 100.0, 585),
        (160, "INTERVENCION GASISTA", 27), (160, 400.0, 360),
        (172, "MATRICULADO", 20),
        (184, "E.P.E.C.", 27), (184, 500.0, 360),
        (196, "Total de Gastos del Período: 09/2025", 20), (196, 900.0, 340), (196, 900.0, 540),
        (220, "FONDO DE RESERVA INGRESOS EGRESOS", 175),
        (232, "SALDO INICIAL 'FONDO DE RESERVA' AL 09/2025", 20), (232, 10.0, 495),
        (244, "Intereses", 20), (244, 5.0, 495),
        (256, "168 MANO DE OBRA", 20), (256, 12.0, 585),
        (268, "SALDO FINAL 'FONDO DE RESERVA' AL 08/2026", 15), (268, 3.0, 585),
        (290, "Saldo Disponible del consorcio $", 21), (290, 153.0, 330),
    ])  # fmt: skip
    b = parse_balance(p)
    assert (b.desde, b.hasta, b.saldo_inicial, b.total_gastos, b.saldo_final) == ("2025-09", "2026-08", 100, 900, 150)
    assert b.ingresos == [("EXPENSAS COMUNES", 1000.0)] and b.egresos == [("pasado a fondo de obra", 50.0)]
    assert [(r.nombre, r.total) for r in b.rubros] == [("SERVICIOS", 900.0)]
    assert b.rubros[0].items == [("INTERVENCION GASISTA MATRICULADO", 400.0), ("E.P.E.C.", 500.0)]
    assert (b.fondo.nombre, b.fondo.saldo_inicial, b.fondo.saldo_final) == ("FONDO DE RESERVA", 10, 3)
    assert b.fondo.ingresos == [("Intereses", 5.0)] and b.fondo.egresos == [("168 MANO DE OBRA", 12.0)]
    assert b.cierre == {"Saldo Disponible del consorcio": 153.0}
    assert arithmetic(b) == []


def _bal(**kw):
    b = Balance(source="x", desde="2025-09", hasta="2026-08", saldo_inicial=100, ingresos=[("EXP", 1000)],
                total_gastos=900, saldo_final=200, rubros=[Rubro("R", 900, [("E.P.E.C.", 900)])],
                fondo=Fund("FONDO", 10, [], [("168 MANO DE OBRA", 4)], 6))  # fmt: skip
    for k, v in kw.items():
        setattr(b, k, v)
    return b


def test_arithmetic_flags_what_does_not_add_up():
    assert arithmetic(_bal()) == []
    problems = arithmetic(_bal(saldo_final=250, rubros=[Rubro("R", 900, [("E.P.E.C.", 800)])]))
    assert any("saldo final" in p for p in problems) and any("rubro R" in p for p in problems)
    assert any("13 meses" in p for p in arithmetic(_bal(desde="2025-08")))


def test_continuity_between_ejercicios():
    prev = _bal(desde="2024-09", hasta="2025-08", saldo_final=100, fondo=Fund("FONDO", 0, [], [], 10))
    assert continuity(prev, _bal()) == []
    out = continuity(prev, _bal(saldo_inicial=90, fondo=Fund("FONDO", 12, [], [], 6)))
    assert len(out) == 2 and "-10,00" in out[0] and "2,00" in out[1]


def test_reconcile_with_liquidaciones_by_concepto_and_fund():
    def liq(*lines):
        return SimpleNamespace(lines=[SimpleNamespace(concepto=c, importe=v, fondo=f) for c, v, f in lines])

    months = _bal().months()
    liqs = {p: liq() for p in months}
    liqs["2025-09"] = liq(("E.P.E.C.", 900, False), ("MANO DE OBRA", 4, True))
    assert reconcile(_bal(), liqs) == ([], [])
    liqs["2025-10"] = liq(("E.P.E.C.", 1, False))
    problems, _ = reconcile(_bal(), liqs)
    assert any(p.startswith("E.P.E.C.") for p in problems)
    del liqs["2026-08"]
    assert reconcile(_bal(), liqs)[1] == ["2026-08"]


def test_ejercicio_runs_september_to_august():
    assert ejercicio("2025-09") == "2025-09" and ejercicio("2026-08") == "2025-09" and ejercicio("2026-09") == "2026-09"


def test_year_pass_proposes_a_late_receipt_of_the_same_ejercicio():
    line = LineRef(1, "2026-03", 5000.0, "SERVICIO TELEFONICO celular", None)
    # Dated before the line, handed in five months later: outside the usual window.
    late = TicketRef(10, "2026-02", 5000.0, "Telefonía celular recibo", None, bundle_period="2026-08")
    links = match([line], [late])
    assert [(x.ticket_id, x.status, x.reason) for x in links] == [(10, "pending", "mismo importe, otro mes del ejercicio")]
    # Never a receipt dated after the gasto, nor one of another ejercicio.
    after = TicketRef(11, "2026-05", 5000.0, "Telefonía celular recibo", None, bundle_period="2026-08")
    other = TicketRef(12, "2025-07", 5000.0, "Telefonía celular recibo", None, bundle_period="2026-08")
    assert match([line], [after, other]) == []
    # Two equally close candidates: left for a human.
    twin = TicketRef(13, "2026-02", 5000.0, "Telefonía celular recibo", None, bundle_period="2026-08")
    assert match([line], [late, twin]) == []
