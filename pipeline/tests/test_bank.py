"""Bank statements inside receipts PDFs: parsing, balance check, payment matching. Invented data only."""

import pytest

from alas3 import bank
from alas3.match import LineRef, collect_movements, match_payments, movement_text
from alas3.schemas import Comprobantes, DocumentManifest, PageRecord, ReviewState

SH = "­"  # the statement's minus sign (soft hyphen)

HEAD = """RESUMEN DE CUENTA CORRIENTE
Banco Ejemplo S.A. Cuit: 30000000007  CONS EJEMPLO
Cuenta  : 1234/5
Período Desde  : 01/03/2026  Saldo
Loc: CORDOBA  Período Hasta  : 31/03/2026  Saldo :  {final}
Fecha  Comprobante  Concepto  Descripción  Importe"""

PAGE1 = f"""{{head}}
01/03/2026  SALDO AL INICIO  1.000.000,00
01/03/2026  127  COM.MANTENIMIENTO CUENTA MENSUAL  {SH}10.000,00
01/03/2026  130  I.V.A.  {SH}2.100,00
Saldo al 01/03/2026  987.900,00
Fecha  Comprobante  Concepto  Descripción  Importe
02/03/2026  111  190  TRANSF.INTERB.DISTINTO TIT. 30711111119 PINTURERIA DEMO SA  {SH}50.000,00
02/03/2026  111  148  IMPUESTO LEY 25413  {SH}300,00
02/03/2026  0039  290  TRANSF.INTER.DISTINTO TIT.{SH}[oculto]{SH}PEREZ, ANA {SH} Dato no  200.000,00
disponible
Fecha de Impresión:  01/04/2026  Hoja:  1/2"""

PAGE2 = f"""{{head}}
05/03/2026  222  146  DEBITO DIRECTO EPEC{SH}0001/02{SH}ELECTRICID  {SH}80.000,00
05/03/2026  333  193  COM. ONLINE SIRO LINK PAGOS  {SH}1.600,00
Saldo al 05/03/2026  1.056.000,00
DE INTERES PARA USTED"""


def pages(final="1.056.000,00", page2=PAGE2):
    head = HEAD.format(final=final)
    return [(7, PAGE1.format(head=head)), (8, page2.format(head=head))]


def test_parses_debits_groups_charges_and_never_keeps_credits():
    st = bank.parse(pages())
    assert (st.banco, st.cuenta, st.desde, st.hasta) == (
        "Banco Ejemplo S.A.",
        "1234/5",
        "2026-03-01",
        "2026-03-31",
    )
    assert (st.saldo_inicial, st.saldo_final, st.creditos) == (1_000_000, 1_056_000, 200_000)
    debits = [m for m in st.movements if m.kind == "debito"]
    assert [(m.fecha, m.importe, m.page_nos) for m in debits] == [
        ("2026-03-02", 50_000, [7]),
        ("2026-03-05", 80_000, [8]),
    ]
    assert debits[0].descripcion == "TRANSF.INTERB.DISTINTO TIT. 30711111119 PINTURERIA DEMO SA"
    (fees,) = [m for m in st.movements if m.kind == "gastos"]
    assert fees.importe == 10_000 + 2_100 + 300 + 1_600
    assert fees.fecha == "2026-03-31" and fees.page_nos == [7, 8]
    assert {i.descripcion for i in fees.items} == {
        "COM. MANTENIMIENTO CUENTA MENSUAL",
        "I.V.A.",
        "IMPUESTO LEY 25413",
        "COM. ONLINE SIRO LINK PAGOS",
    }
    # The owner's payment (a credit) is only in the total, never a movement.
    assert not any("PEREZ" in m.descripcion for m in st.movements)


def test_unbalanced_statement_fails_closed():
    with pytest.raises(bank.StatementError, match="closing balance"):
        bank.parse(pages(final="1.056.000,01"))
    # A missed row shows up at the next daily checkpoint.
    with pytest.raises(bank.StatementError, match="Saldo al"):
        bank.parse(
            pages(
                page2=PAGE2.replace(f"05/03/2026  333  193  COM. ONLINE SIRO LINK PAGOS  {SH}1.600,00\n", "")
            )
        )


def _manifest(texts: dict[int, str]) -> DocumentManifest:
    return DocumentManifest(
        id=9,
        kind="comprobantes",
        period="2026-03",
        title="t",
        source_name="c.pdf",
        sha256="ab" * 32,
        pages=[PageRecord(page_no=n, text=t, ocr_engine="pdf-text") for n, t in texts.items()],
    )


def test_statements_in_a_document_and_failed_pages_reported():
    good = _manifest(dict(pages()) | {9: "Factura C"})
    st, failed = bank.statements(good)
    assert len(st) == 1 and st[0].page_nos == [7, 8] and failed == []
    bad = _manifest(dict(pages(final="1,00")))
    assert bank.statements(bad) == ([], [7, 8])


def test_restricted_pages_are_never_read():
    m = _manifest(dict(pages()))
    m.pages[1].restricted = True
    st, failed = bank.statements(m)
    # Page 8 alone is skipped; page 7 alone does not balance: nothing is used.
    assert st == [] and failed == [7]


def test_movement_text_keeps_only_the_payee():
    assert (
        movement_text("TRANSF.INTERB.DISTINTO TIT. 30708573082 PASTORINO SEGURIDAD SRL")
        == "PASTORINO SEGURIDAD SRL"
    )
    assert movement_text("TRANSF.INTERB.PAGO DE HABER [oculto] PEREZ JUAN") == "PEREZ JUAN"


def test_payments_match_lines_exactly_and_never_as_sums(monkeypatch):
    m = _manifest(dict(pages()))
    ext = Comprobantes(tickets=[], bank=bank.statements(m)[0])
    monkeypatch.setattr("alas3.extract.load_extract", lambda _m: ext)
    refs, lookup = collect_movements([m])
    by_text = {r.text: r for r in refs}
    lines = [
        LineRef(1, "2026-03", 50_000, "COMPRA DE MATERIAL Pinturería Demo", None),
        LineRef(2, "2026-04", 14_100, "GS. BANCARIOS COBRANZAS mes 03/2026", None),  # next month, near amount
        LineRef(3, "2026-03", 130_000, "Varios", None),  # = 50.000 + 80.000: must not become a sum
    ]
    links = {x.line_id: x for x in match_payments(lines, refs)}
    assert links[1].status == "auto" and links[1].ticket_id == by_text["PINTURERIA DEMO SA"].id
    assert links[2].status == "pending" and lookup[links[2].ticket_id][1].kind == "gastos"
    assert 3 not in links
    # Decisions come from review.payments, not from the receipt links.
    review = ReviewState(payments={f"1:{links[1].ticket_id}": "rejected"},
                         links={f"1:{links[1].ticket_id}": "verified"})  # fmt: skip
    assert 1 not in {x.line_id for x in match_payments(lines, refs, review)}


def test_publish_sql_has_debits_and_links_but_no_owner_payments(monkeypatch):
    from alas3.publish import _bank_sql

    m = _manifest(dict(pages()))
    ext = Comprobantes(tickets=[], bank=bank.statements(m)[0])
    monkeypatch.setattr("alas3.extract.load_extract", lambda _m: ext)
    monkeypatch.setattr("alas3.publish.load_extract", lambda _m: ext)
    sql = "\n".join(_bank_sql([m], [LineRef(1, "2026-03", 50_000, "Pinturería Demo", None)], ReviewState()))
    assert sql.count("INSERT INTO bank_movements") == 3  # 2 debits + the grouped charges
    assert "PEREZ" not in sql and "200000" not in sql
    assert "INSERT INTO expense_payment_links VALUES (1, " in sql
    assert sql.index("DELETE FROM expense_payment_links") < sql.index("INSERT INTO bank_movements")
