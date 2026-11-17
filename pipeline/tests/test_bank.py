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


@pytest.fixture(autouse=True)
def private_texts(tmp_path, monkeypatch):
    """bank.statements reads the private full text ingest keeps; here: one file per page."""
    monkeypatch.setattr(bank, "private_text_path", lambda m, n: tmp_path / f"{m.work_dir_name}-p{n}.bank.txt")


def _manifest(texts: dict[int, str]) -> DocumentManifest:
    """Public page text = what ingest publishes (credit rows removed); private copy = all of it."""
    for n, t in texts.items():
        lines = t.split("\n")
        bank.private_text_path(_SHELL, n).write_text(t)
        texts[n] = "\n".join(x for i, x in enumerate(lines) if i not in bank.credit_lines(lines))
    return DocumentManifest(
        id=9,
        kind="comprobantes",
        period="2026-03",
        title="t",
        source_name="c.pdf",
        sha256="ab" * 32,
        pages=[PageRecord(page_no=n, text=t, ocr_engine="pdf-text") for n, t in texts.items()],
    )


_SHELL = DocumentManifest(id=9, kind="comprobantes", title="t", source_name="c.pdf", sha256="ab" * 32)


def test_credit_rows_and_their_wrapped_lines_are_found():
    lines = PAGE1.format(head=HEAD.format(final="1,00")).split("\n")
    hidden = [lines[i] for i in sorted(bank.credit_lines(lines))]
    assert hidden == [x for x in lines if "PEREZ" in x] + ["disponible"]
    # Footer text after the last row is never taken as part of a description.
    assert not any("Impresión" in lines[i] for i in bank.credit_lines(lines))


def test_footer_and_legal_text_are_not_appended_to_descriptions():
    page2 = PAGE2.replace(
        "DE INTERES PARA USTED", "Cuenta sujeta a condiciones generales\nDE INTERES PARA USTED"
    )
    page2 = page2.replace(
        f"{SH}80.000,00\n", f"{SH}80.000,00\nVer condiciones en www.banco.example: 0800 123\n"
    )
    st = bank.parse(pages(page2=page2))
    epec = next(m for m in st.movements if "EPEC" in m.descripcion)
    assert "condiciones" not in epec.descripcion and "0800" not in epec.descripcion


@pytest.mark.parametrize("minus", ["-", "\u2013", "\u2212", SH])
def test_every_minus_sign_variant(minus):
    st = bank.parse(pages(page2=PAGE2.replace(f"{SH}80.000,00", f"{minus}80.000,00")))
    assert any(m.importe == 80_000 for m in st.movements)


def test_salary_and_refund_debits_are_published_without_the_name():
    extra = (f"05/03/2026  444  256  TRANSF.INTERB.PAGO DE HABER [oculto] GOMEZ JUAN  {SH}10.000,00\n"
             f"05/03/2026  445  190  TRANSF.INTERB.DISTINTO TIT. [oculto] DEVOLUCION LOPEZ ANA  {SH}5.000,00\n")  # fmt: skip
    page2 = PAGE2.replace("Saldo al 05/03/2026  1.056.000,00", extra + "Saldo al 05/03/2026  1.041.000,00")
    st = bank.parse(pages(final="1.041.000,00", page2=page2))
    descs = [m.descripcion for m in st.movements]
    assert "Pago de haberes" in descs and "Reintegro o devolución" in descs
    assert not any("GOMEZ" in d or "LOPEZ" in d for d in descs)


def test_checkpoint_at_the_top_of_the_next_page():
    page1 = PAGE1.replace(
        "Fecha de Impresión", "02/03/2026  0  148  IMPUESTO LEY 25413  " + SH + "0,00\nFecha de Impresión"
    )
    page2 = PAGE2.replace("{head}\n", "{head}\nSaldo al 02/03/2026  1.137.600,00\n")
    assert bank.parse(pages(page2=page2)).saldo_final == 1_056_000
    assert bank.parse([(7, page1.format(head=HEAD.format(final="1.056.000,00"))), pages(page2=page2)[1]])


def test_statements_in_a_document_and_failed_pages_reported():
    good = _manifest(dict(pages()) | {9: "Factura C"})
    st, failed = bank.statements(good)
    assert len(st) == 1 and st[0].page_nos == [7, 8] and failed == []
    bad = _manifest(dict(pages(final="1,00")))
    assert bank.statements(bad) == ([], [7, 8])


def test_two_accounts_and_a_page_without_header():
    head2 = HEAD.replace("1234/5", "9999/1")
    second = [
        (9, PAGE1.format(head=head2.format(final="1.056.000,00"))),
        (10, PAGE2.format(head=head2.format(final="1.056.000,00"))),
    ]
    # A continuation page without the period header still belongs to its statement.
    first = pages()
    first[1] = (8, first[1][1].replace("Período Desde", "Desde").replace("Período Hasta", "Hasta"))
    st, failed = bank.statements(_manifest(dict(first + second)))
    assert [(s.cuenta, s.page_nos) for s in st] == [("1234/5", [7, 8]), ("9999/1", [9, 10])] and failed == []


def test_two_opening_balances_in_one_group_fail_closed():
    with pytest.raises(bank.StatementError, match="second opening"):
        bank.parse(pages() + [(9, PAGE1.format(head=HEAD.format(final="1.056.000,00")))])


def test_missing_private_text_fails_closed(tmp_path):
    m = _manifest(dict(pages()))
    for n in (7, 8):
        bank.private_text_path(m, n).unlink()
    assert bank.statements(m) == ([], [7, 8])


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


def test_ingested_statement_never_publishes_owner_payments(data_dir):
    """End to end: page text, search index, PDF and publish SQL hold no owner's payment."""
    import pymupdf

    from alas3 import extract, ingest, publish
    from tests.conftest import make_pdf
    from tests.test_pipeline import migrated_db

    head = HEAD.format(final="1.056.000,00").split("\n")
    p1 = [x.replace(SH, "-") for x in PAGE1.format(head="\n".join(head)).split("\n")]
    p2 = [x.replace(SH, "-") for x in PAGE2.format(head="\n".join(head)).split("\n")]
    make_pdf(data_dir / "inbox/comprobantes/Comprobantes_proveedores_202603.pdf", [p1, p2])
    (m,) = ingest.ingest_all()
    ext = extract.extract_document(m)
    assert [len(s.movements) for s in ext.bank] == [3] and ext.untranscribed == []

    assert not any("PEREZ" in p.text or "200.000" in p.text for p in m.pages)
    assert m.pages[0].hidden_lines == 2  # the payment row and its wrapped line
    with pymupdf.open(ingest.doc_dir(m) / "public.pdf") as doc:
        assert "PEREZ" not in doc[0].get_text() and "PINTURERIA DEMO" in doc[0].get_text()

    sql = publish.build_sql(ingest.load_manifests())
    assert "PEREZ" not in sql and "200.000" not in sql
    db = migrated_db()
    db.executescript(sql)
    db.executescript((publish.REPO / "db/rebuild_fts.sql").read_text())
    assert db.execute("SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH 'perez'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM bank_movements").fetchone()[0] == 3


def test_a_credit_we_cannot_split_into_columns_is_still_hidden():
    assert bank.credit_lines(["02/03/2026 PAGO PEREZ ANA 200.000,00", "disponible"]) == {0, 1}
    with pytest.raises(bank.StatementError, match="unreadable"):
        bank.parse(pages(page2=PAGE2.replace("05/03/2026  222  146  DEBITO", "05/03/2026  DEBITO")))


def test_movements_whose_pages_became_private_are_not_published(monkeypatch):
    """Review: a stale extract must not publish movements from pages restricted since."""
    from alas3.publish import _bank_sql

    m = _manifest(dict(pages()))
    ext = Comprobantes(tickets=[], bank=bank.statements(m)[0])
    for p in m.pages:
        p.restricted = True
    monkeypatch.setattr("alas3.extract.load_extract", lambda _m: ext)
    monkeypatch.setattr("alas3.publish.load_extract", lambda _m: ext)
    line = LineRef(1, "2026-03", 50_000, "Pinturería Demo", None)
    sql = "\n".join(_bank_sql([m], [line], ReviewState()))
    assert "INSERT INTO bank_movements" not in sql and "INSERT INTO expense_payment_links" not in sql


def test_a_dash_ending_the_description_is_not_a_minus_sign():
    """Real credit rows end their description with a dash: "LINK PAGOS SIRO -  420.000,00"."""
    assert bank.row_kinds(["09/12/2025  226302578  497  LINK PAGOS SIRO -  420.000,00"]) == ["credit"]
    assert bank.row_kinds([f"09/12/2025  226302578  497  COM. LINK  {SH}420,00"]) == ["debit"]


def test_salary_and_refund_rows_are_blacked_out_on_the_page_too():
    lines = [
        f"05/03/2026  444  256  TRANSF.INTERB.PAGO DE HABER [oculto] GOMEZ JUAN  {SH}10.000,00",
        "ANDRES",
        f"05/03/2026  445  190  TRANSF.INTERB.DISTINTO TIT. 30711111119 PINTURERIA DEMO SA  {SH}5.000,00",
        "05/03/2026  0039  290  TRANSF.INTER.DISTINTO TIT. PEREZ, ANA  200.000,00",
        f"05/03/2026  446  190  TRANSF.INTERB.DISTINTO TIT. [oculto] REINTEGRO LOPEZ  {SH}1.000,00",
        "Saldo al 05/03/2026  1.000,00",
    ]
    assert bank.private_lines(lines) == {0, 1, 3, 4}
