from alas3.match import LineRef, Link
from alas3.review import line_coverage


def _line(lid: int, importe: float, period: str = "2026-10") -> LineRef:
    return LineRef(id=lid, period=period, importe=importe, text="", subcategoria=None)


def test_receipts_partial_then_settled():
    lines = [_line(1, 300.0)]
    totals = {10: 100.0, 11: 120.0, 12: 80.0}
    cov = line_coverage(lines, [Link(1, 10, 1.0, "verified")], [], totals, {}, payment_periods=set())[1]
    r = cov["ticket"]
    assert (r["covered"], r["remaining"], r["settled"]) == (100.0, 200.0, False)
    assert cov["missing"] == ["ticket"]
    links = [Link(1, t, 1.0, "verified") for t in totals]
    cov = line_coverage(lines, links, [], totals, {}, payment_periods=set())[1]
    assert cov["settled"] and cov["missing"] == [] and len(cov["items"]) == 3


def test_line_needs_receipt_and_payment():
    lines = [_line(1, 100.0)]
    receipt_only = line_coverage(lines, [Link(1, 5, 1.0, "verified")], [], {5: 100.0}, {})[1]
    assert receipt_only["missing"] == ["payment"] and not receipt_only["settled"]
    payment_only = line_coverage(lines, [], [Link(1, 7, 1.0, "auto")], {}, {7: 100.0})[1]
    assert payment_only["missing"] == ["ticket"]
    both = line_coverage(
        lines, [Link(1, 5, 1.0, "verified")], [Link(1, 5, 1.0, "auto")], {5: 100.0}, {5: 100.0}
    )[1]
    assert both["settled"] and both["missing"] == []
    assert {i["type"] for i in both["items"]} == {"ticket", "payment"}
    assert all(i["shared"] == 1 for i in both["items"])  # same id on both sides is not "shared"


def test_receipt_and_payment_do_not_add_up():
    cov = line_coverage(
        [_line(1, 100.0)], [Link(1, 5, 1.0, "verified")], [Link(1, 6, 1.0, "verified")], {5: 40.0}, {6: 60.0}
    )[1]
    assert cov["ticket"]["remaining"] == 60.0 and cov["payment"]["remaining"] == 40.0
    assert cov["missing"] == ["ticket", "payment"]


def test_payment_only_needed_with_a_bank_statement():
    lines = [_line(1, 100.0, "2026-10"), _line(2, 100.0, "2026-12")]
    cov = line_coverage(lines, [], [], {}, {}, payment_periods={"2026-09"}, receipt_periods={"2026-11"})
    assert (
        not cov[1]["payment"]["needed"] and cov[1]["missing"] == []
    )  # a september statement does not ask october for a payment
    assert cov[2]["ticket"]["needed"] and cov[2]["missing"] == [
        "ticket"
    ]  # receipts of the month before count


def test_shared_receipt_is_capped():
    lines = [_line(1, 70.0), _line(2, 30.0)]
    links = [Link(1, 10, 1.0, "verified"), Link(2, 10, 1.0, "verified")]
    cov = line_coverage(lines, links, [], {10: 100.0}, {})
    assert cov[1]["ticket"]["covered"] == 70.0 and cov[2]["ticket"]["covered"] == 30.0
    assert cov[1]["items"][0]["shared"] == 2


def test_pending_side_is_proposed_not_missing():
    cov = line_coverage(
        [_line(1, 50.0)], [Link(1, 10, 0.7, "pending")], [], {10: 50.0}, {}, payment_periods=set()
    )[1]
    r = cov["ticket"]
    assert r["covered"] == 0.0 and r["proposed"] == 50.0 and r["pending"]
    assert cov["missing"] == [] and not cov["settled"]


def test_bank_charges_are_their_own_receipt():
    cov = line_coverage([_line(1, 120.0)], [], [Link(1, 9, 1.0, "auto")], {}, {9: 120.0}, self_proving={9})[1]
    assert cov["ticket"]["settled"] and cov["payment"]["settled"] and cov["missing"] == []
    assert len(cov["items"]) == 1  # shown once, as the bank movement


def test_rejection_keeps_its_reason_until_undone(tmp_path, monkeypatch):
    import pytest

    from alas3 import review

    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "review.json")
    review.apply({"type": "payment", "line_id": "7", "movement_id": "9", "decision": "rejected",
                  "motivo": "corresponde a otro gasto", "detalle": " es la cuota 1 "})  # fmt: skip
    state = review.load_review()
    assert state.payments == {"7:9": "rejected"}
    note = state.notes["payment:7:9"]
    assert (note.motivo, note.detalle) == ("corresponde a otro gasto", "es la cuota 1")
    # Undoing the rejection drops its reason; a receipt link uses its own namespace.
    review.apply({"type": "payment", "line_id": "7", "movement_id": "9", "decision": None})
    assert review.load_review().notes == {}
    with pytest.raises(ValueError):  # only the listed reasons
        review.apply(
            {
                "type": "payment",
                "line_id": "7",
                "movement_id": "9",
                "decision": "rejected",
                "motivo": "porque sí",
            }
        )
    assert review.load_review().payments == {}  # nothing half-saved


def test_original_page_is_local_only_and_never_for_restricted_pages(data_dir):
    import importlib

    from alas3 import ingest
    from tests.conftest import make_pdf

    review = importlib.import_module("alas3.review")
    make_pdf(data_dir / "inbox/comprobantes/Comprobantes_proveedores_202603.pdf",
             [["Factura C", "Total 1.234,00"], ["Otra página"]])  # fmt: skip
    (m,) = ingest.ingest_all()
    doc = m.work_dir_name
    assert review._original(doc, 1).startswith(b"\x89PNG")
    assert review._original(doc, 3) is None and review._original("../etc/passwd", 1) is None
    # A page that is (or becomes) restricted is never rendered, not even locally.
    m.pages[1].restricted = True
    (ingest.doc_dir(m) / "manifest.json").write_text(m.model_dump_json())
    assert review._original(doc, 2) is None


def test_private_receipt_shows_only_its_crops(data_dir):
    import importlib

    import pytest
    from pydantic import ValidationError

    from alas3 import ingest
    from alas3.schemas import PrivateCrop, PrivateReceipt, TicketTranscription
    from tests.conftest import make_pdf

    review = importlib.import_module("alas3.review")
    receipts = importlib.import_module("alas3.receipts")
    make_pdf(data_dir / "inbox/comprobantes/Comprobantes_proveedores_202603.pdf",
             [["Factura C", "Total 1.234,00"], ["Costo laboral", "TOTAL 500,00"]])  # fmt: skip
    (m,) = ingest.ingest_all()
    doc = m.work_dir_name
    crop = PrivateCrop(campo="importe", x0=0.1, y0=0.1, x1=0.6, y1=0.15)
    tr = TicketTranscription(private_receipts=[
        PrivateReceipt(page=2, concepto="SUSS + sindicatos + seguro", total=500.0, crops=[crop]),
    ])  # fmt: skip
    receipts.transcription_path(m).parent.mkdir(parents=True, exist_ok=True)
    receipts.transcription_path(m).write_text(tr.model_dump_json())
    # Only for a restricted page (where private receipts live).
    assert review._private_crop(doc, 0, 0) is None
    m.pages[1].restricted = True
    (ingest.doc_dir(m) / "manifest.json").write_text(m.model_dump_json())
    assert review._private_crop(doc, 0, 0).startswith(b"\x89PNG")
    assert review._private_crop(doc, 0, 1) is None and review._private_crop(doc, 1, 0) is None
    assert review._original(doc, 2) is None  # the whole page still never
    (t,) = [t for t in receipts.build(m).tickets if t.privado]
    assert review._private_crops(m, t) == [{"url": f"/priv/{doc}/0/0.png", "campo": "importe"}]
    # A crop is a box around one amount, never (most of) the page.
    with pytest.raises(ValidationError):
        PrivateCrop(campo="importe", x0=0, y0=0, x1=1, y1=0.5)


def test_rejecting_keeps_the_undecided_siblings(tmp_path, monkeypatch):
    from alas3 import review

    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "review.json")
    review.save_review(review.ReviewState(links={"1:11": "verified"}))
    review.apply({"type": "link", "line_id": "1", "ticket_id": "10", "decision": "rejected",
                  "motivo": "otro mes", "keep": ["11", "12"]})  # fmt: skip
    # The confirmed one stays confirmed; the undecided one is kept as a proposal.
    assert review.load_review().links == {"1:11": "verified", "1:10": "rejected", "1:12": "pending"}


def test_closing_a_month_is_saved_and_reopens(tmp_path, monkeypatch):
    import pytest

    from alas3 import review

    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "review.json")
    monkeypatch.setattr(review, "queue", lambda: {"months": []})  # nothing open anywhere
    review.apply({"type": "month", "period": "2026-03", "closed": True})
    review.apply({"type": "month", "period": "2026-01", "closed": True})
    review.apply({"type": "month", "period": "2026-03", "closed": True})  # twice: once
    assert review.load_review().closed_months == ["2026-01", "2026-03"]
    review.apply({"type": "month", "period": "2026-03", "closed": False})
    assert review.load_review().closed_months == ["2026-01"]
    with pytest.raises(ValueError):
        review.apply({"type": "month", "period": "2026-13", "closed": True})


def test_accepted_difference_settles_only_within_it():
    from alas3.review import line_coverage

    ln = _line(1, 10_000.0)
    links = [Link(1, 50, 1.0, "verified")]
    accepted = {"1:receipt": 120.0}
    cov = line_coverage([ln], links, [], {50: 9_880.0}, {}, payment_periods=set(), accepted=accepted)[1]
    assert cov["ticket"]["settled"] and cov["ticket"]["accepted"] == 120.0 and cov["settled"]
    # More missing than accepted (a receipt unlinked): not settled any more.
    cov = line_coverage([ln], links, [], {50: 9_000.0}, {}, payment_periods=set(), accepted=accepted)[1]
    assert not cov["ticket"]["settled"]
    # Never without evidence linked.
    cov = line_coverage([ln], [], [], {}, {}, payment_periods=set(), accepted=accepted)[1]
    assert not cov["ticket"]["settled"] and cov["ticket"]["accepted"] is None


def test_accept_diff_action(tmp_path, monkeypatch):
    from alas3 import review

    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "review.json")
    review.apply(
        {"type": "accept_diff", "line_id": "7", "side": "payment", "importe": 120, "detalle": " redondeo "}
    )
    d = review.load_review().accepted_diffs["7:payment"]
    assert (d.importe, d.detalle) == (120.0, "redondeo")
    review.apply({"type": "accept_diff", "line_id": "7", "side": "payment", "importe": None})
    assert review.load_review().accepted_diffs == {}


def test_a_month_with_anything_open_cannot_be_closed(tmp_path, monkeypatch):
    import pytest

    from alas3 import review

    monkeypatch.setattr(review, "REVIEW_FILE", tmp_path / "review.json")
    monkeypatch.setattr(
        review, "queue", lambda: {"months": [{"period": "2026-10", "blockers": ["1 movimientos sin gasto"]}]}
    )
    with pytest.raises(ValueError, match="movimientos sin gasto"):
        review.apply({"type": "month", "period": "2026-10", "closed": True})
    assert review.load_review().closed_months == []


def test_month_status_lists_what_is_open():
    from types import SimpleNamespace as NS

    from alas3.review import month_status

    lines = [_line(1, 100.0), _line(2, 50.0)]
    side = lambda settled, pending=False: {"settled": settled, "pending": pending}  # noqa: E731
    cover = {1: {"settled": True, "ticket": side(True), "payment": side(True)},
             2: {"settled": False, "ticket": side(False, True), "payment": side(True)}}  # fmt: skip
    tickets = [
        NS(id=10, period="2026-09", bundle_period="2026-10"),
        NS(id=11, period=None, bundle_period="2026-10"),
    ]
    movements = [NS(id=20, period="2026-10")]
    rows = month_status(lines, cover, tickets, movements, {10}, {20}, verified={10}, closed=set())
    oct_, sep = rows
    assert oct_["period"] == "2026-10" and not oct_["ready"]
    assert oct_["blockers"] == ["1 gastos sin cubrir", "1 gastos con propuestas para revisar",
                                "1 comprobantes sin gasto", "1 comprobantes sin verificar"]  # fmt: skip
    assert sep == {**sep, "period": "2026-09", "ready": True, "blockers": [], "receipts": 1}
