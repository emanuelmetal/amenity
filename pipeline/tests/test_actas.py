"""Actas: photos of the handwritten book -> 1-page documents + one transcription file."""

import json
import sqlite3

import pytest
from PIL import Image
from pydantic import ValidationError

from tests.test_pipeline import liquidacion_pdf, migrated_db


def photo(path, color=(240, 240, 230)):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (300, 520), color)
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make: must not survive into the published PDF
    im.save(path, format="JPEG", exif=exif, comment=b"PhoneComment")
    return path


def write_book(data_dir, book: dict):
    f = data_dir / "work" / "extract" / "actas.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(book))


def test_untranscribed_photo_is_restricted_and_not_rendered(data_dir):
    from alas3 import actas, ingest

    photo(data_dir / "inbox/actas/WhatsApp Image 1.jpeg")
    [m] = ingest.ingest_all()
    assert m.kind == "acta" and len(m.pages) == 1
    assert m.pages[0].restricted and m.pages[0].restricted_reason == "untranscribed"
    assert not (ingest.doc_dir(m) / "p001.webp").exists()
    import pymupdf

    with pymupdf.open(ingest.doc_dir(m) / "public.pdf") as doc:  # the document row is published: blank PDF
        assert not doc[0].get_images() and "no publicado" in doc[0].get_text()
    assert any("to transcribe" in line and m.work_dir_name in line for line in actas.report([m]))


def test_transcribed_photo_published_as_is_without_metadata(data_dir):
    import pymupdf

    from alas3 import ingest

    p = photo(data_dir / "inbox/actas/a.jpeg")
    sha16 = ingest.sha256_file(p)[:16]
    write_book(data_dir, {"folios": {sha16: {"folio": 265, "texto": "Acta 101. Se reúne la comisión. CUIL 20-12345678-3"}}})
    [m] = ingest.ingest_all()
    page = m.pages[0]
    assert not page.restricted and page.ocr_engine == "manual"
    assert m.title == "Libro de actas, folio 265"
    assert "12345678" not in page.text  # transcribed text still goes through redact_text
    out = ingest.doc_dir(m)
    assert (out / "p001.webp").exists()
    pdf = (out / "public.pdf").read_bytes()
    assert b"PhoneMaker" not in pdf and b"PhoneComment" not in pdf
    with pymupdf.open(out / "public.pdf") as doc:
        assert len(doc) == 1 and not any(doc.metadata.get(k) for k in ("author", "creator", "producer", "title"))


def test_scanned_acta_pdf_private_until_transcribed_and_blacked_out(data_dir):
    import pymupdf

    from alas3 import ingest

    pdf = data_dir / "inbox/actas/acta.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 280), False)
        pix.set_rect(pix.irect, (255, 255, 255))
        page.insert_image(page.rect, pixmap=pix)
    doc.save(pdf)
    [m] = ingest.ingest_all()
    assert [p.restricted_reason for p in m.pages] == ["untranscribed", "untranscribed"]
    sha16 = m.work_dir_name
    write_book(data_dir, {"folios": {f"{sha16}#1": {"texto": "Asamblea. DNI 12.345.678",
                                                     "checked": [{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2, "motivo": "DNI"}]}},
                          "titulos": {sha16: "Asamblea ordinaria"}})
    [m] = ingest.ingest_all()
    p1, p2 = m.pages
    assert not p1.restricted and "12.345.678" not in p1.text and p2.restricted_reason == "untranscribed"
    assert m.title == "Asamblea ordinaria"
    out = ingest.doc_dir(m)
    assert (out / "p001.webp").exists() and not (out / "p002.webp").exists()
    with pymupdf.open(out / "public.pdf") as d:
        px = d[0].get_pixmap(dpi=72)
        r = d[0].rect
        assert px.pixel(int(r.width * 0.3), int(r.height * 0.15)) == (0, 0, 0)  # blacked out
        assert px.pixel(int(r.width * 0.8), int(r.height * 0.8)) == (255, 255, 255)
        assert not d[1].get_images()  # private page blanked
    with pytest.raises(ValidationError):  # book photos never get blackouts
        from alas3.schemas import ActaBook

        ActaBook.model_validate({"folios": {sha16: {"texto": "x", "checked": [{"x0": 0, "y0": 0, "x1": 1, "y1": 1}]}}})


def test_book_validation():
    from alas3.schemas import ActaBook

    folio = {"folio": 1, "texto": "x"}
    acta = {"numero": 1, "fecha": "2025-11-27", "folios": ["0123456789abcdef"], "resumen": "r"}
    ActaBook.model_validate({"folios": {"0123456789abcdef": folio}, "actas": [acta]})
    with pytest.raises(ValidationError):  # folio not transcribed
        ActaBook.model_validate({"folios": {}, "actas": [acta]})
    with pytest.raises(ValidationError):  # duplicated acta
        ActaBook.model_validate({"folios": {"0123456789abcdef": folio}, "actas": [acta, acta]})
    with pytest.raises(ValidationError):  # bad key
        ActaBook.model_validate({"folios": {"photo.jpeg": folio}})


def test_obra_validation():
    from alas3.schemas import ActaBook, Obra

    assert Obra(nombre="A", aprobado=1000).total_aprobado == 1000
    assert Obra(nombre="A", cuota_por_unidad=10, cuotas=3).total_aprobado == 10 * 3 * 64
    assert Obra(nombre="A").total_aprobado is None and Obra(nombre="A").criterio is None
    with pytest.raises(ValidationError):  # both ways of stating the amount
        Obra(nombre="A", aprobado=1, cuota_por_unidad=1, cuotas=1)
    with pytest.raises(ValidationError):  # cuota without the number of cuotas
        Obra(nombre="A", cuota_por_unidad=1)
    folio = {"folio": 1, "texto": "x"}
    acta = {"numero": 1, "fecha": "2025-11-27", "folios": ["0123456789abcdef"], "resumen": "r"}
    base = {"folios": {"0123456789abcdef": folio}, "actas": [acta]}
    ActaBook.model_validate({**base, "obras": [{"nombre": "A", "actas": ["1"]}]})
    with pytest.raises(ValidationError):  # unknown acta
        ActaBook.model_validate({**base, "obras": [{"nombre": "A", "actas": ["7"]}]})
    with pytest.raises(ValidationError):  # duplicated obra
        ActaBook.model_validate({**base, "obras": [{"nombre": "A"}, {"nombre": "A"}]})


def test_publish_actas_links_and_leaves_comments_alone(data_dir):
    from alas3 import extract, ids, ingest, publish
    from alas3.schemas import ReviewState

    liquidacion_pdf(data_dir / "inbox/ResumenGastos_012026.pdf")
    a = photo(data_dir / "inbox/actas/a.jpeg")
    b = photo(data_dir / "inbox/actas/b.jpeg", color=(200, 200, 200))
    c = photo(data_dir / "inbox/actas/c.jpeg", color=(100, 100, 100))  # not transcribed
    sa, sb, sc = (ingest.sha256_file(x)[:16] for x in (a, b, c))
    # first ingest to learn the liquidación's line ids
    for m in ingest.ingest_all():
        extract.extract_document(m)
    liq = next(m for m in ingest.load_manifests() if m.kind == "liquidacion")
    lines = ids.expense_line_ids(extract.load_extract(liq))
    book = {
        "folios": {sa: {"folio": 265, "texto": "Acta 101 ..."}, sb: {"folio": 266, "texto": "... fin. Acta 102"}},
        "actas": [
            {"numero": 101, "fecha": "2025-11-27", "folios": [sa, sb], "resumen": "Apertura de sobres",
             "asistentes": ["4 integrantes de la comisión"],
             "items": [{"tipo": "decision", "texto": "Contratar la limpieza", "importe": 90000,
                        "gastos": [lines[0], 999]}]},
            {"numero": 102, "fecha": "2026-03-02", "folios": [sb], "resumen": "Obra de terrazas"},
        ],
        "obras": [
            {"nombre": "Terrazas", "cuota_por_unidad": 50000, "cuotas": 2, "actas": ["102"],
             "gastos": [lines[0], 999], "observaciones": ["2026-01-01"], "detalle": "El administrador cobró dos cuotas."},
        ],
    }
    write_book(data_dir, book)
    manifests = ingest.ingest_all()
    for m in manifests:
        extract.extract_document(m)
    assert {m.work_dir_name for m in manifests if m.kind == "acta" and m.pages[0].restricted} == {sc}

    db = migrated_db()
    db.execute("INSERT INTO comments (entity_type, entity_id, body, author_key) VALUES ('acta', 1, 'hola', 'k')")
    from alas3.actas import load_book

    sql = publish.build_sql(ingest.load_manifests(), ReviewState(actas_verified=["102"]), book=load_book())
    db.executescript(sql)
    db.row_factory = sqlite3.Row
    rows = {r["numero"]: r for r in db.execute("SELECT * FROM actas")}
    assert set(rows) == {101, 102}
    photos = {m.work_dir_name: m for m in ingest.load_manifests()}
    assert json.loads(rows[101]["page_ids_json"]) == [photos[sa].page_id(1), photos[sb].page_id(1)]
    assert rows[101]["verified"] == 0 and rows[102]["verified"] == 1
    assert rows[101]["id"] == ids.stable_id("acta", "101")
    assert [r[0] for r in db.execute("SELECT expense_line_id FROM acta_expense_links")] == [lines[0]]
    assert db.execute("SELECT count(*) FROM comments").fetchone()[0] == 1
    assert "comments" not in sql
    obra = db.execute("SELECT * FROM obras").fetchone()
    assert obra["id"] == ids.stable_id("obra", "Terrazas")
    assert obra["aprobado"] == 50000 * 2 * 64
    assert obra["criterio"] == "$ 50.000 por unidad × 64 unidades × 2 cuotas"
    assert json.loads(obra["acta_ids_json"]) == [rows[102]["id"]]
    assert json.loads(obra["observation_ids_json"]) == ["2026-01-01"]
    assert [r[0] for r in db.execute("SELECT expense_line_id FROM obra_expense_links")] == [lines[0]]  # 999 dropped
    # republishing replaces them in full
    db.executescript(sql)
    assert db.execute("SELECT count(*) FROM obras").fetchone()[0] == 1
    # the untranscribed photo's page is restricted and not searchable; the acta is
    assert db.execute("SELECT restricted FROM pages WHERE id = ?", (photos[sc].page_id(1),)).fetchone()[0] == 1
    hits = db.execute("SELECT entity_type FROM search_fts WHERE search_fts MATCH 'sobres'").fetchall()
    assert ("acta",) in [tuple(h) for h in hits]


def test_review_marks_an_acta_verified(data_dir):
    from alas3 import review

    write_book(data_dir, {"folios": {"0123456789abcdef": {"folio": 1, "texto": "x"}},
                          "actas": [{"numero": 7, "fecha": "2026-01-02", "folios": ["0123456789abcdef"], "resumen": "r"}]})
    review.apply({"type": "acta", "key": "7", "verified": True})
    assert review.load_review().actas_verified == ["7"]
    review.apply({"type": "acta", "key": "7", "verified": False})
    assert review.load_review().actas_verified == []
    with pytest.raises(ValueError):
        review.apply({"type": "acta", "key": "8", "verified": True})


def test_restrict_json_withholds_a_transcribed_folio(data_dir):
    import pymupdf

    from alas3 import actas, ingest

    p = photo(data_dir / "inbox/actas/a.jpeg")
    sha16 = ingest.sha256_file(p)[:16]
    write_book(data_dir, {"folios": {sha16: {"folio": 9, "texto": "DNI en la foto"}}})
    (data_dir / "work" / "restrict.json").write_text(json.dumps({sha16: {"restrict": [1]}}))
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted and m.pages[0].restricted_reason == "manual" and m.pages[0].text == ""
    assert not (ingest.doc_dir(m) / "p001.webp").exists()
    with pymupdf.open(ingest.doc_dir(m) / "public.pdf") as doc:
        assert not doc[0].get_images()
    first = (ingest.doc_dir(m) / "public.pdf").read_bytes()
    ingest.ingest_all()
    assert (ingest.doc_dir(m) / "public.pdf").read_bytes() == first  # stable: no re-upload
    assert not any("to transcribe" in line for line in actas.report([m]))


def test_article_ids_are_stable_across_publishes():
    from alas3.ids import article_ids
    from alas3.schemas import ReglamentoArticle

    arts = [ReglamentoArticle(numero=n, orden=i, texto="t", page_nos=[1]) for i, n in enumerate(["1", "2", "3"], 1)]
    ids = article_ids("0123456789abcdef", arts)
    assert article_ids("0123456789abcdef", arts[1:]) == ids[1:]  # dropping one keeps the others
