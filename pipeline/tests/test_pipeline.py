import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pymupdf
import pytest

from alas3 import links
from tests.conftest import make_pdf

REPO = Path(__file__).resolve().parents[2]
CUIL = "20-12345678-3"


def migrated_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    for f in sorted((REPO / "db/migrations").glob("*.sql")):
        db.executescript(f.read_text())
    return db


def liquidacion_pdf(path: Path) -> Path:
    """Synthetic page in the administrator's real layout, debt list at the bottom."""
    return make_pdf(
        path,
        [
            [
                ("Total de Gastos del Mes", "1.090.000,00"),
                "DETALLE DE LOS GASTOS AL MES: ENERO DE 2026",
                "SUELDOS Y JORNALES",
                ("SUELDO ENCARGADO", "CUIL " + CUIL, "1,000,000.00"),
                "SERVICIOS Y SERVICES",
                ("E.P.E.C.", "fact. con vto. 01/2026", "90,000.00"),
                ("Total de Gastos del Período: 01/2026", "1,090,000.00"),
                "Unidades con deudas al: 01/2026",
                ("9/A 901  111.111,00", "8/H 802  222.222,00"),
                ("6/E 603  333.333,00", "5/F 504  444.444,00"),
                "VENCIMIENTO DE LAS EXPENSAS COMUNES: 12/02/2026",
            ],
            ["RECIBO DE HABERES", "Sueldo basico 900.000,00"],
        ],
    )


def test_ingest_policy_redacted_pdf_and_renders(data_dir):
    from alas3 import ingest

    pdf = liquidacion_pdf(data_dir / "inbox/ResumenGastos_012026.pdf")
    [m] = ingest.ingest_all()
    assert m.kind == "liquidacion" and m.period == "2026-01"
    assert m.title == "Liquidación de expensas 2026-01"
    p1, p2 = m.pages
    # page 1 stays published, with the debt block and the CUIL removed everywhere
    assert not p1.restricted and p1.hidden_lines >= 3 and p1.redacted_strings == 1
    assert "333.333" not in p1.text and "9/A" not in p1.text
    assert "12345678" not in p1.text and "E.P.E.C." in p1.text
    assert "12345678" in ingest.raw_text(m, 1)  # extraction still sees everything, locally
    # page 2 (payroll) restricted, never rendered
    assert p2.restricted and p2.restricted_reason == "payroll" and p2.text == ""
    d = ingest.doc_dir(m)
    assert (d / "p001.webp").exists() and not (d / "p002.webp").exists()

    with pymupdf.open(d / "public.pdf") as doc:
        t1, t2 = doc[0].get_text(), doc[1].get_text()
        assert "E.P.E.C." in t1
        for secret in ("12345678", "333.333", "9/A 901", "Unidades con deudas"):
            assert secret not in t1, secret
        assert "HABERES" not in t2 and "privacidad" in t2
        assert not any(v for v in doc.metadata.values() if v and v != "PDF 1.7")

    assert ingest.ingest_file(pdf, "liquidacion").id == m.id  # cached and stable


def test_scanned_page_without_text_fails_closed(data_dir, monkeypatch):
    from alas3 import ingest, ocr

    monkeypatch.setattr(ocr, "ocr_document", lambda *_: None)  # OCR missing/failed
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), 0))
    doc.save(data_dir / "inbox/reglamento/escaneado.pdf")
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted and m.pages[0].restricted_reason == "no_text"
    assert not (ingest.doc_dir(m) / "p001.webp").exists()


def test_manual_overrides(data_dir, monkeypatch):
    from alas3 import ingest, ocr

    monkeypatch.setattr(ocr, "ocr_document", lambda *_: None)
    pdf = make_pdf(
        data_dir / "inbox/reglamento/r.pdf", [["ARTICULO 1: uno dos tres cuatro cinco seis siete ocho"]] * 2
    )
    sha16 = ingest.sha256_file(pdf)[:16]
    (data_dir / "work").mkdir(exist_ok=True)
    (data_dir / "work/restrict.json").write_text(json.dumps({sha16: {"restrict": [2]}}))
    [m] = ingest.ingest_all()
    assert [p.restricted_reason for p in m.pages] == [None, "manual"]


def test_full_override_publishes_a_page_unredacted(data_dir, monkeypatch):
    from alas3 import ingest, ocr

    monkeypatch.setattr(ocr, "ocr_document", lambda *_: None)
    text = f"ARTICULO 1: el titular CUIL {CUIL} declara lo siguiente"
    pdf = make_pdf(data_dir / "inbox/reglamento/r.pdf", [[text], [text], [text]])
    sha16 = ingest.sha256_file(pdf)[:16]
    (data_dir / "work").mkdir(exist_ok=True)
    # Page 2: the owner decided to publish it as sent; page 3: restrict wins over full.
    (data_dir / "work/restrict.json").write_text(json.dumps({sha16: {"full": [2, 3], "restrict": [3]}}))
    [m] = ingest.ingest_all()
    p1, p2, p3 = m.pages
    assert CUIL not in p1.text and p1.redacted_strings == 1  # the automatic masking, as always
    assert CUIL in p2.text and not p2.restricted and p2.redacted_strings == 0
    assert p3.restricted_reason == "manual"
    with pymupdf.open(ingest.doc_dir(m) / "public.pdf") as pub:
        assert CUIL not in pub[0].get_text() and CUIL in pub[1].get_text()  # no blackout on page 2


def test_only_phase_kinds_are_ingested_and_published(data_dir):
    from alas3 import ingest, publish

    make_pdf(data_dir / "inbox/039_20250922102519_Circulares Varias.pdf", [["Circular con datos de vecinos"]])
    make_pdf(data_dir / "inbox/acta_2026-09-15.pdf", [["Acta de la comision"]])
    [m] = ingest.ingest_all()  # an acta is ingested, but private until transcribed (actas.py)
    assert m.kind == "acta" and m.pages[0].restricted_reason == "untranscribed"
    sql = publish.build_sql(ingest.load_manifests())
    assert "Circular" not in sql and "Acta de la comision" not in sql


def test_publish_sql_redacted_and_per_document(data_dir):
    from alas3 import extract, ingest, publish

    make_pdf(
        data_dir / "inbox/039_20250922100437_Reglamento Interno.pdf",
        [["ARTICULO 1: DEL OBJETO. Texto O'Brien uno"], ["ARTICULO 2: Mascotas permitidas"]],
    )
    make_pdf(
        data_dir / "inbox/039_20260211151324_Reglamento de Copropiedad.pdf",
        [["ARTICULO 1: DE LOS PROPIETARIOS. Juan Perez D.N.I. 12.345.678 es titular"]],
    )
    liquidacion_pdf(data_dir / "inbox/ResumenGastos_012026.pdf")
    for m in ingest.ingest_all():
        extract.extract_document(m)
    sql = publish.build_sql(ingest.load_manifests())

    # H1: no person identifier survives in anything published
    assert "12345678" not in sql and "12.345.678" not in sql

    db = migrated_db()
    db.executescript(sql)
    db.executescript(sql)  # idempotent

    titles = {r[0] for r in db.execute("SELECT title FROM documents")}
    assert {"Reglamento Interno", "Reglamento de Copropiedad", "Liquidación de expensas 2026-01"} <= titles
    # M2: both reglamentos keep their articles
    per_doc = dict(db.execute("SELECT document_id, COUNT(*) FROM reglamento_articles GROUP BY document_id"))
    assert sorted(per_doc.values()) == [1, 2]
    assert (
        db.execute("SELECT texto FROM reglamento_articles WHERE texto LIKE '%Brien%'").fetchone()[0]
        == "Texto O'Brien uno"
    )
    lines = db.execute(
        "SELECT concepto, detalle, importe FROM expense_lines ORDER BY importe DESC"
    ).fetchall()
    assert lines == [
        ("SUELDO ENCARGADO", "CUIL [oculto]", 1_000_000.0),
        ("E.P.E.C.", "fact. con vto. 01/2026", 90_000.0),
    ]
    assert db.execute("SELECT total FROM periods").fetchone()[0] == 1_090_000.0
    assert db.execute("SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH 'haberes'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH '\"797\"'").fetchone()[0] == 0
    hit = db.execute(
        "SELECT title FROM search_fts WHERE search_fts MATCH 'mascotas' AND entity_type='article'"
    ).fetchone()
    assert hit[0].startswith("Reglamento Interno · Artículo 2")


def test_publish_reuploads_changed_files_and_deletes_restricted_renders(data_dir, monkeypatch):
    from alas3 import extract, ingest, publish

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(publish.wrangler, "r2_put", lambda key, *a: calls.append(("put", key)))
    monkeypatch.setattr(publish.wrangler, "r2_delete", lambda key, *a: calls.append(("delete", key)))
    monkeypatch.setattr(publish.wrangler, "d1_file", lambda *a: calls.append(("d1", "")))
    from alas3 import ask_sync

    monkeypatch.setattr(ask_sync, "sync", lambda local: calls.append(("ask", "")))

    pdf = make_pdf(
        data_dir / "inbox/reglamento/r.pdf",
        [["ARTICULO 1: uno dos tres cuatro cinco seis"], ["ARTICULO 2: siete ocho nueve diez once doce"]],
    )
    [m] = ingest.ingest_all()
    extract.extract_document(m)
    publish.publish(local=True)
    assert sorted(k for op, k in calls if op == "put") == sorted(
        [publish.pdf_key(m), publish.page_key(m, 1), publish.page_key(m, 2)]
    )

    calls.clear()
    publish.publish(local=True)  # nothing changed: nothing re-sent
    assert [c for c in calls if c[0] not in ("d1", "ask")] == []

    # A reviewer restricts page 2 later: the PDF must be re-sent and the render removed, after D1.
    sha16 = ingest.sha256_file(pdf)[:16]
    (data_dir / "work/restrict.json").write_text(json.dumps({sha16: {"restrict": [2]}}))
    [m] = ingest.ingest_all(force=True)
    calls.clear()
    publish.publish(local=True)
    assert calls == [("put", publish.pdf_key(m)), ("d1", ""), ("ask", ""), ("delete", publish.page_key(m, 2))]


def test_period_and_kind_from_real_file_names():
    from alas3.ingest import classify_name, guess_period

    assert guess_period("ResumenGastos_012026.pdf") == "2026-01"
    assert guess_period("Comprobantes_proveedores_202601.pdf") == "2026-01"
    assert guess_period("2026-10_liquidacion.pdf") == "2026-10"
    assert guess_period("x.pdf", "Saldo Inicial del Período 03/2026  1,00") == "2026-03"
    assert guess_period("039_20260211151324_Reglamento de Copropiedad.pdf") is None
    assert classify_name("039_20260211151324_Reglamento de Copropiedad.pdf") == "reglamento"
    assert classify_name("ResumenGastos_012026.pdf") == "liquidacion"
    assert classify_name("Comprobantes_proveedores_202601.pdf") == "comprobantes"
    assert classify_name("039_20250922102519_Circulares Varias.pdf") == "otro"


def test_links_hash_and_sql():
    token, h = links.new_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert h == hashlib.sha256(token.encode()).hexdigest()
    sql = links.insert_sql(h, "unit", "UF12", 30)
    assert token not in sql and h in sql and "'UF12'" in sql
    db = migrated_db()
    db.executescript(sql)
    assert db.execute("SELECT kind, unit_label, active FROM access_codes").fetchone() == ("unit", "UF12", 1)


def test_links_reject_injection_in_unit_label():
    with pytest.raises(SystemExit):
        links.insert_sql("a" * 64, "unit", "UF1'); DROP TABLE x;--", None)


def test_remote_links_require_https_site_url(monkeypatch):
    monkeypatch.delenv("ALAS3_SITE_URL", raising=False)
    with pytest.raises(SystemExit):
        links.site_url(local=False)
    monkeypatch.setenv("ALAS3_SITE_URL", "https://torre3.example/")
    assert links.site_url(local=False) == "https://torre3.example"
    assert links.site_url(local=True).startswith("http://localhost")


def _image_page(doc: pymupdf.Document, lines: list[str], stamp: str | None = None) -> None:
    """Adds a page that is only a picture of `lines` (a scan), optionally with a tiny text stamp."""
    tmp = pymupdf.open()
    p = tmp.new_page()
    for k, ln in enumerate(lines):
        p.insert_text((72, 100 + 22 * k), ln, fontsize=16)
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=p.get_pixmap(dpi=200))
    if stamp:
        page.insert_text((500, 820), stamp, fontsize=6)


def test_scan_with_only_a_text_stamp_stays_private(data_dir, monkeypatch):
    """Review #3: ocrmypdf --skip-text leaves stamped scans unread; they must not be published."""
    from alas3 import ingest, ocr

    monkeypatch.setattr(
        ocr, "ocr_document", lambda src, dest: None
    )  # same effect as --skip-text on that page
    doc = pymupdf.open()
    _image_page(doc, ["RECIBO DE HABERES", f"CUIL {CUIL}"], stamp="Pag 2")
    doc.save(data_dir / "inbox/reglamento/sellado.pdf")
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted_reason == "no_text"


def test_image_inside_a_digital_page_is_checked(data_dir, monkeypatch):
    """Review #3: a pasted payroll scan inside a born-digital page is OCR'd from pixels."""
    from alas3 import ingest, ocr

    monkeypatch.setattr(ocr, "ocr_page_pixels", lambda page: "RECIBO DE HABERES\nSueldo basico 900.000,00")
    doc = pymupdf.open()
    _image_page(doc, ["RECIBO DE HABERES"])
    doc[0].insert_text(
        (72, 60), "ARTICULO 1: texto digital suficiente para no ser un escaneo puro", fontsize=9
    )
    doc.save(data_dir / "inbox/reglamento/mixto.pdf")
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted_reason == "payroll"

    monkeypatch.setattr(ocr, "ocr_page_pixels", lambda page: "")  # OCR unavailable: fail closed
    [m] = ingest.ingest_all(force=True)
    assert m.pages[0].restricted_reason == "no_text"


def test_hidden_debt_rows_never_become_expense_lines(data_dir):
    """Review #2: generic layout with a debt block that the parser's own markers don't know."""
    from alas3 import extract, ingest

    make_pdf(
        data_dir / "inbox/liquidaciones/2026-02_liq.pdf",
        [
            [
                "RUBRO 1 - LIMPIEZA",
                ("Articulos de limpieza", "1.000,00"),
                ("TOTAL GENERAL", "1.000,00"),
                "Detalle de deudas por U.F.",
                ("UF 12  Juan Perez", "123.456,78"),
                "Nota final del administrador",
            ]
        ],
    )
    [m] = ingest.ingest_all()
    assert not m.pages[0].restricted and m.pages[0].hidden_lines >= 2
    liq = extract.extract_document(m)
    assert [ln.concepto for ln in liq.lines] == ["Articulos de limpieza"]
    assert "Perez" not in ingest.raw_text(m, 1)


def test_identifier_that_cannot_be_located_restricts_the_page(data_dir, monkeypatch):
    """Review #5: masked in text but not found in the PDF → the image would still show it."""
    from alas3 import ingest

    monkeypatch.setattr(pymupdf.Page, "search_for", lambda self, s, **k: [])
    make_pdf(
        data_dir / "inbox/reglamento/r.pdf", [[f"ARTICULO 1: el titular CUIL {CUIL} declara lo siguiente"]]
    )
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted_reason == "unlocated_identifier"


def test_malformed_overrides_fail_loudly(data_dir):
    """Review #6."""
    from alas3 import ingest

    pdf = make_pdf(
        data_dir / "inbox/reglamento/r.pdf", [["ARTICULO 1: uno dos tres cuatro cinco seis siete"]]
    )
    (data_dir / "work").mkdir(exist_ok=True)
    sha16 = ingest.sha256_file(pdf)[:16]
    for bad in (
        {sha16: {"restrict": ["x"]}},
        {"0123456789abcdef": {"restrict": [1]}},
        {sha16: {"hide": [1]}},
    ):
        (data_dir / "work/restrict.json").write_text(json.dumps(bad))
        with pytest.raises(SystemExit):
            ingest.ingest_all()


def test_failed_extraction_does_not_leave_stale_results(data_dir):
    """Review #9."""
    from alas3 import extract, ingest

    make_pdf(data_dir / "inbox/liquidaciones/sin_periodo.pdf", [["RUBRO 1 - X", ("Algo", "1,00")]])
    [m] = ingest.ingest_all()
    (ingest.doc_dir(m) / "extract.json").write_text("{}")
    with pytest.raises(ValueError):
        extract.extract_document(m)
    assert not (ingest.doc_dir(m) / "extract.json").exists()


def test_publish_sweeps_documents_no_longer_published(data_dir):
    """Review #8: rows of documents that left the published set are deleted."""
    from alas3 import ingest, publish

    make_pdf(data_dir / "inbox/reglamento/r.pdf", [["ARTICULO 1: uno dos tres cuatro cinco seis siete"]])
    ingest.ingest_all()
    db = migrated_db()
    db.executescript(
        "INSERT INTO documents (id, kind, title, r2_key_pdf, sha256, pages) VALUES (99, 'otro', 'viejo', 'k', 's', 1);"
        "INSERT INTO pages (id, document_id, page_no, r2_key_img) VALUES (990001, 99, 1, 'k');"
        "INSERT INTO reglamento_articles (numero, orden, texto) VALUES ('1', 1, 'sin documento');"
    )
    db.executescript(publish.build_sql(ingest.load_manifests()))
    assert db.execute("SELECT COUNT(*) FROM documents WHERE id = 99").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM pages WHERE document_id = 99").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM reglamento_articles WHERE document_id IS NULL").fetchone()[0] == 0


def test_expense_line_ids_are_stable_and_links_survive_republish(data_dir):
    """Phase 2: re-ingesting keeps line ids, so review decisions about them still apply."""
    from alas3 import ingest, publish
    from alas3.ids import expense_line_ids
    from alas3.schemas import Liquidacion, LiquidacionLine

    liq = Liquidacion(
        period="2026-10",
        lines=[
            LiquidacionLine(rubro="R", concepto="Taxi", importe=10.0),
            LiquidacionLine(rubro="R", concepto="Taxi", importe=10.0),  # identical line, distinct id
        ],
    )
    a, b = expense_line_ids(liq)
    assert a != b and expense_line_ids(liq) == [a, b]

    make_pdf(
        data_dir / "inbox/liquidaciones/liq_2026-10.pdf",
        [
            [
                "RUBRO 1 - MANTENIMIENTO",
                ("Pintura", "100,00"),
                "TOTAL RUBRO 1  100,00",
                "TOTAL GASTOS DEL MES  100,00",
            ]
        ],
    )
    from alas3 import cli

    cli.main(["ingest"])
    db = migrated_db()
    sql = publish.build_sql(ingest.load_manifests())
    db.executescript(sql)
    (lid,) = db.execute("SELECT id FROM expense_lines").fetchone()
    cli.main(["ingest", "--force"])  # re-extract from scratch: same line, same id
    db.executescript(publish.build_sql(ingest.load_manifests()))
    assert db.execute("SELECT id FROM expense_lines").fetchall() == [(lid,)]
    from alas3.schemas import ReviewState

    db.executescript(publish.build_sql(ingest.load_manifests(), ReviewState(lines_verified=[lid])))
    assert db.execute("SELECT verified FROM expense_lines WHERE id = ?", (lid,)).fetchone() == (1,)
