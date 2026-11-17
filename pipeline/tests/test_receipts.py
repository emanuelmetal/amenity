"""Receipts: ARCA QR decoding, QR blackout, copy merging, transcription merge. Invented data only."""

import base64
import json

import cv2
import pymupdf
import pytest

from alas3.qr import find_qr, parse_arca
from tests.conftest import make_pdf

# Invented voucher: a person (monotributo) vendor, so the QR holds a CUIL.
FIELDS = {"ver": 1, "fecha": "2026-01-15", "cuit": 20111111112, "ptoVta": 3, "tipoCmp": 11,
          "nroCmp": 1234, "importe": 4800.5, "moneda": "PES", "ctz": 1, "codAut": 70000000000001}  # fmt: skip


def arca_url(fields=FIELDS) -> str:
    return "https://www.arca.gob.ar/fe/qr/?p=" + base64.b64encode(json.dumps(fields).encode()).decode()


def qr_png(text: str, scale: int = 8) -> bytes:
    img = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(img, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", img)[1].tobytes()


def invoice_pdf(path, copies=("ORIGINAL", "DUPLICADO"), rotate=0, payload=None):
    doc = pymupdf.open()
    for copy in copies:
        page = doc.new_page()
        page.insert_text(
            (72, 72), f"{copy}  FACTURA C  Punto de Venta: 00003  Comp. Nro: 00001234", fontsize=10
        )
        page.insert_text((72, 90), "Importe Total: $ 4800,50", fontsize=10)
        page.insert_image(pymupdf.Rect(60, 600, 200, 740), stream=qr_png(payload or arca_url()))
        page.set_rotation(rotate)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def test_parse_arca_payload():
    f = parse_arca(arca_url())
    assert f == {"fecha": "2026-01-15", "cuit": "20111111112", "pto_vta": 3, "tipo_cmp": 11,
                 "nro_cmp": 1234, "total": 4800.5, "cae": "70000000000001"}  # fmt: skip
    # Unpadded base64 and the old AFIP host also work.
    p = base64.urlsafe_b64encode(json.dumps(FIELDS).encode()).decode().rstrip("=")
    assert parse_arca("https://www.afip.gob.ar/fe/qr/?p=" + p)["nro_cmp"] == 1234
    # Older AFIP URL, and numbers with leading zeros (invalid JSON some issuers emit).
    raw = json.dumps(FIELDS).replace('"nroCmp": 1234', '"nroCmp": 00001234')
    old = (
        "https://serviciosweb.afip.gob.ar/genericos/comprobantes/cae.aspx?p="
        + base64.b64encode(raw.encode()).decode()
    )
    assert parse_arca(old)["nro_cmp"] == 1234
    # Other QRs are not invoices.
    for other in ("https://evil.example/fe/qr/?p=" + p, "https://eqrcode.co/a/x", "00020101021243", None, ""):
        assert parse_arca(other) is None


@pytest.mark.parametrize("rotate", [0, 90])
def test_qr_found_then_blacked_out_in_public_pdf(data_dir, rotate):
    from alas3 import ingest

    invoice_pdf(data_dir / "inbox/comprobantes/c_2026-01.pdf", rotate=rotate)
    [m] = ingest.ingest_all()
    d = ingest.doc_dir(m)
    payloads = json.loads((d / "raw/qr.json").read_text())
    assert payloads["1"] == [arca_url()] and all(p.has_qr for p in m.pages)
    with pymupdf.open(d / "public.pdf") as pub:
        for page in pub:
            assert find_qr(page) == []  # the QR (which encodes a CUIL) is gone from the published PDF
    for p in m.pages:
        img = cv2.imread(str(d / f"p{p.page_no:03d}.webp"), cv2.IMREAD_GRAYSCALE)
        assert img is not None
        ok, *_ = cv2.QRCodeDetector().detectAndDecodeMulti(img)
        assert not ok


def test_copies_merge_into_one_ticket_and_transcription_fills_vendor(data_dir):
    from alas3 import extract, ingest, receipts

    invoice_pdf(data_dir / "inbox/comprobantes/c_2026-01.pdf", copies=("ORIGINAL", "DUPLICADO", "TRIPLICADO"))
    make_pdf(data_dir / "inbox/comprobantes/x_2026-01.pdf", [["Recibo manuscrito sin QR"], ["Extracto"]])
    ms = {m.source_name: m for m in ingest.ingest_all()}
    inv, scan = ms["c_2026-01.pdf"], ms["x_2026-01.pdf"]

    receipts.transcription_path(inv).parent.mkdir(parents=True, exist_ok=True)
    receipts.transcription_path(inv).write_text(json.dumps({"tickets": [{
        "page_nos": [1], "proveedor": "Electricista Uno", "descripcion": "Cambio de lámparas",
        "pto_vta": 3, "nro_cmp": 1234, "tipo_cmp": 11, "total": 99.0,  # wrong total: the QR must win
    }]}))  # fmt: skip
    res = extract.extract_document(inv)
    [t] = res.tickets
    assert t.page_nos == [1, 2, 3] and t.source == "qr" and t.total == 4800.5
    assert (t.proveedor, t.kind, t.letra, t.period) == ("Electricista Uno", "factura", "C", "2026-01")
    assert t.subcategoria == "Electricidad" and res.untranscribed == []

    # Without a transcription, pages with no QR are reported as still to transcribe.
    assert extract.extract_document(scan).untranscribed == [1, 2]
    receipts.transcription_path(scan).write_text(json.dumps({
        "tickets": [{"page_nos": [1], "kind": "presupuesto", "proveedor": "Ferretería", "total": 1500, "fecha": "2026-01-10"}],
        "other_pages": {"2": "extracto bancario"},
    }))  # fmt: skip
    res = extract.extract_document(scan)
    assert res.untranscribed == [] and res.tickets[0].source == "llm"


def test_bad_transcription_fails_loudly(data_dir):
    from alas3 import extract, ingest, receipts

    make_pdf(data_dir / "inbox/comprobantes/x_2026-01.pdf", [["Recibo"]])
    [m] = ingest.ingest_all()
    receipts.transcription_path(m).parent.mkdir(parents=True, exist_ok=True)
    receipts.transcription_path(m).write_text(json.dumps({"tickets": [{"page_nos": [1], "totl": 5}]}))
    with pytest.raises(ValueError):
        extract.extract_document(m)


def test_debt_block_does_not_carry_across_receipt_pages(data_dir):
    from alas3 import ingest

    make_pdf(
        data_dir / "inbox/comprobantes/c_2026-01.pdf",
        [
            ["Extracto", "Tasa de interés sobre saldos deudores 70 %", "pie"],
            ["Factura", "Total 100,00", "Gracias"],
        ],
    )
    [m] = ingest.ingest_all()
    assert not m.pages[1].restricted and m.pages[1].hidden_lines == 0


def test_receipt_on_restricted_page_is_not_published(data_dir):
    from alas3 import extract, ingest, receipts

    make_pdf(data_dir / "inbox/comprobantes/c_2026-01.pdf", [["RECIBO DE HABERES", "Sueldo básico 1.000,00"]])
    [m] = ingest.ingest_all()
    assert m.pages[0].restricted_reason == "payroll"
    receipts.transcription_path(m).parent.mkdir(parents=True, exist_ok=True)
    receipts.transcription_path(m).write_text(json.dumps({"tickets": [{"page_nos": [1], "total": 1000}]}))
    assert extract.extract_document(m).tickets == []


def test_small_second_qr_on_a_page_is_also_blacked_out(data_dir):
    """Review M1: a page with a big and a small QR (two receipts) loses both."""
    from alas3 import ingest

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(60, 60, 260, 260), stream=qr_png(arca_url(), scale=10))
    other = dict(FIELDS, nroCmp=99, importe=10.0)
    page.insert_image(pymupdf.Rect(400, 600, 450, 650), stream=qr_png(arca_url(other), scale=3))
    path = data_dir / "inbox/comprobantes/c_2026-01.pdf"
    doc.save(path)
    with pymupdf.open(path) as src:
        assert len(find_qr(src[0])) == 2
    [m] = ingest.ingest_all()
    with pymupdf.open(ingest.doc_dir(m) / "public.pdf") as pub:
        assert find_qr(pub[0]) == []


def test_receipt_partly_on_a_private_page_is_not_published(data_dir):
    """Review M4: data read from a payroll page must not be published via a public cover page."""
    from alas3 import extract, ingest, receipts

    make_pdf(
        data_dir / "inbox/comprobantes/c_2026-01.pdf",
        [["RECIBO DE HABERES", "Sueldo básico 1.000,00"], ["Carátula"]],
    )
    [m] = ingest.ingest_all()
    receipts.transcription_path(m).parent.mkdir(parents=True, exist_ok=True)
    receipts.transcription_path(m).write_text(json.dumps({"tickets": [{"page_nos": [1, 2], "total": 1000}]}))
    assert extract.extract_document(m).tickets == []


def test_ticket_ids_do_not_depend_on_cuit_or_total():
    """Review H1/M3: a masked CUIL must not be recoverable from the id; editing a total keeps it."""
    from alas3.ids import ticket_ids
    from alas3.schemas import Ticket

    a = Ticket(page_nos=[1], pto_vta=3, nro_cmp=1234, cuit="20111111112", total=10)
    b = Ticket(page_nos=[1], pto_vta=3, nro_cmp=1234, cuit=None, total=99)
    assert ticket_ids("s", [a]) == ticket_ids("s", [b])
    c, d = Ticket(page_nos=[5], total=10), Ticket(page_nos=[5], total=11)
    assert ticket_ids("s", [c]) == ticket_ids("s", [d])


def test_transcription_field_formats_are_enforced():
    from pydantic import ValidationError

    from alas3.schemas import Ticket

    for bad in ({"letra": "B'; DROP"}, {"cae": "abc"}, {"total": float("nan")}, {"period": "enero"}):
        with pytest.raises(ValidationError):
            Ticket(page_nos=[1], **bad)


def test_implausible_located_only_qr_is_ignored():
    """A located-only detection the size of half the page is noise, not a QR to black out."""
    from alas3.qr import plausible_qr

    page = pymupdf.open().new_page()  # 595 x 842
    assert plausible_qr(page, pymupdf.Rect(60, 600, 140, 680))  # 80pt square: an invoice QR
    assert not plausible_qr(page, pymupdf.Rect(0, 0, 400, 480))  # most of the page
    assert not plausible_qr(page, pymupdf.Rect(0, 0, 1600, 30000))  # garbage geometry
    assert not plausible_qr(page, pymupdf.Rect(60, 600, 160, 620))  # a thin strip


def test_invoice_without_a_located_qr_fails_closed(data_dir):
    """Review: a page that mentions a CAE but whose QR was not found is not published."""
    from alas3 import ingest

    path = data_dir / "inbox/comprobantes/c_2026-01.pdf"
    make_pdf(
        path,
        [
            ["FACTURA C  Comp. Nro: 00001234", "CAE: 70000000000001  Vto. CAE: 25/01/2026"],
            ["Recibo de mano de obra"],
        ],
    )
    [m] = ingest.ingest_all()
    assert [(p.page_no, p.restricted_reason) for p in m.pages] == [(1, "qr_not_located"), (2, None)]


def test_printed_cuit_from_the_qr_is_blacked_out_or_the_page_restricted(data_dir):
    """Review: OCR may misread the printed CUIT; the QR gives it exactly."""
    from alas3 import ingest

    def pdf(name, printed):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), f"FACTURA C  CUIT: {printed}  CAE: 70000000000001", fontsize=10)
        page.insert_image(pymupdf.Rect(60, 600, 200, 740), stream=qr_png(arca_url()))
        (data_dir / "inbox/comprobantes").mkdir(parents=True, exist_ok=True)
        doc.save(data_dir / "inbox/comprobantes" / name)

    pdf("a_2026-01.pdf", "20 11111111 2")  # spaced: still found from the QR's exact digits
    pdf("b_2026-02.pdf", "2O-1111111I-2")  # misread: cannot be located on the page
    by_name = {m.source_name: m for m in ingest.ingest_all()}
    a, b = by_name["a_2026-01.pdf"], by_name["b_2026-02.pdf"]
    assert not a.pages[0].restricted
    with pymupdf.open(ingest.doc_dir(a) / "public.pdf") as pub:
        assert "11111111" not in pub[0].get_text()
    assert b.pages[0].restricted_reason == "unlocated_identifier"


def test_numeric_codes_written_as_floats():
    f = parse_arca(arca_url(FIELDS | {"codAut": 86172729432629.0, "cuit": 20111111112.0}))
    assert f["cae"] == "86172729432629" and f["cuit"] == "20111111112"
    assert parse_arca(arca_url(FIELDS | {"codAut": "86x"})) is None


def test_same_voucher_number_from_two_vendors_keeps_its_id():
    """Review: ids must not swap when the order of receipts changes (a QR stops decoding)."""
    from alas3.ids import ticket_ids
    from alas3.schemas import Ticket

    a = Ticket(page_nos=[2], pto_vta=1, nro_cmp=123, tipo_cmp=11)
    b = Ticket(page_nos=[9], pto_vta=1, nro_cmp=123)
    ia, ib = ticket_ids("s", [a, b])
    assert ia != ib and ticket_ids("s", [b, a]) == [ib, ia]
    assert ticket_ids("s", [a.model_copy(update={"tipo_cmp": None})]) == [ia]  # type lost with the QR
