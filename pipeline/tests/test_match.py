"""Matching receipts to expense lines, and review decisions. Invented data only."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from alas3.match import AUTO, LineRef, TicketRef, match
from alas3.schemas import ReviewState


def L(i, importe, text, period="2026-01", sub=None):  # noqa: N802
    return LineRef(i, period, importe, text, sub)


def T(i, total, text, period="2026-01", sub=None):  # noqa: N802
    return TicketRef(i, period, total, text, sub)


def by_line(links):
    out = {}
    for x in links:
        out.setdefault(x.line_id, []).append(x)
    return out


def test_unique_exact_amount_links_automatically():
    links = by_line(
        match([L(1, 48000, "MANO DE OBRA ELECTRICISTA Pérez")], [T(10, 48000, "Pérez Juan electricista")])
    )
    assert [(x.ticket_id, x.status) for x in links[1]] == [(10, "auto")] and links[1][0].score >= AUTO


def test_same_amount_twice_goes_to_review():
    links = match(
        [L(1, 4000, "TELEFONO"), L(2, 9999, "OTRA")], [T(10, 4000, "Recibo celular"), T(11, 4000, "Librería")]
    )
    assert by_line(links)[1][0].status == "pending"


def test_several_receipts_sum_to_one_line_and_near_amounts_come_last():
    lines = [L(1, 123456.78, "E.P.E.C. factura"), L(2, 500000, "HONORARIOS"), L(3, 2000, "FOTOCOPIAS")]
    tickets = [
        T(10, 122500.00, "EPEC energía"),
        T(11, 956.78, "EPEC energía"),
        T(12, 502000, "Administración"),
    ]
    links = by_line(match(lines, tickets))
    assert sorted(x.ticket_id for x in links[1]) == [10, 11]  # not the bigger bill alone (within 1%)
    assert links[1][0].status == "auto"  # same vendor on every receipt of the sum
    assert [x.ticket_id for x in links[2]] == [12] and [x.ticket_id for x in links[3]] == [
        12
    ]  # one receipt, two lines
    assert links[2][0].status == "pending"


def test_receipts_from_previous_month_count_but_not_older():
    links = by_line(
        match([L(1, 500, "Taxi", "2026-02")], [T(10, 500, "Taxi", "2026-01"), T(11, 500, "Taxi", "2025-11")])
    )
    assert [x.ticket_id for x in links[1]] == [10]


def test_rejected_pair_is_never_proposed_and_verified_pair_is_kept():
    lines, tickets = [L(1, 100, "Pintura")], [T(10, 100, "Pinturería"), T(11, 55, "Otro")]
    state = ReviewState(links={"1:10": "rejected"})
    assert match(lines, tickets, state) == []
    state = ReviewState(links={"1:11": "verified"})  # a human linked a receipt with another amount
    [x] = match(lines, tickets, state)
    assert (x.ticket_id, x.status) == (11, "verified")


def test_ambiguous_sum_is_left_for_a_human():
    tickets = [T(10, 10, "a"), T(11, 20, "b"), T(12, 30, "c"), T(13, 20, "d")]
    links = match([L(1, 30, "x")], tickets)
    # 30 exact exists (one-to-one) -> fine; but 40 = 10+30 = 20+20: ambiguous, no link
    assert all(x.line_id == 1 for x in links)
    assert match([L(2, 40, "y")], tickets) == []


def test_review_file_rejects_unknown_fields(data_dir):
    from alas3 import review

    review.REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    review.REVIEW_FILE.write_text(json.dumps({"links": {"1:2": "maybe"}}))
    with pytest.raises(ValueError):
        review.load_review()
    review.REVIEW_FILE.write_text(json.dumps({"lnks": {}}))
    with pytest.raises(ValueError):
        review.load_review()


def test_review_server_guards(data_dir):
    from http.server import ThreadingHTTPServer

    from alas3 import review

    # Run the real handler on a free port.
    srv_holder = {}
    orig = ThreadingHTTPServer.__init__

    def capture(self, addr, handler):
        orig(self, ("127.0.0.1", 0), handler)
        srv_holder["srv"] = self

    ThreadingHTTPServer.__init__ = capture
    try:
        th = threading.Thread(target=review.serve, kwargs={"port": 0}, daemon=True)
        th.start()
        while "srv" not in srv_holder:
            pass
    finally:
        ThreadingHTTPServer.__init__ = orig
    srv = srv_holder["srv"]
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"

    def call(path, data=None, headers=None):
        req = urllib.request.Request(base + path, data=data, headers=headers or {})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code

    # The handler was built for port 0, so the real Host header does not match: refused.
    assert call("/") == 403
    # A forged Host matching the configured one passes the host check...
    ok_host = {"Host": "127.0.0.1:0"}
    assert call("/img/../../etc/passwd.webp", headers=ok_host) == 404
    body = json.dumps({"type": "line", "id": 1, "verified": True}).encode()
    # ...but a POST without the custom header is refused (cross-site forms cannot set it).
    assert call("/api/action", body, {**ok_host, "Content-Type": "application/json"}) == 403
    assert call("/api/action", body, {**ok_host, "Content-Type": "application/json", "X-Review": "1"}) == 200
    assert review.load_review().lines_verified == [1]
    srv.shutdown()


def test_confirmed_receipt_keeps_its_remainder_for_other_lines():
    """A user confirms honorarios <-> a receipt for more; the remainder is still proposed for another line."""
    lines = [L(1, 500000, "HONORARIOS ADMINISTRACION"), L(2, 2000, "FOTOCOPIAS"), L(3, 2000, "OTRA COSA")]
    tickets = [T(10, 502000, "Administración: honorarios y fotocopias")]
    links = match(lines, tickets, ReviewState(links={"1:10": "verified"}))
    got = {(x.line_id, x.ticket_id): x.status for x in links}
    assert got[(1, 10)] == "verified"
    assert (2, 10) in got or (3, 10) in got  # the $3.000 left is proposed (two candidates: for review)
    assert all(st == "pending" for k, st in got.items() if k != (1, 10))


def test_manual_link_with_any_amount_is_kept():
    links = match(
        [L(1, 2000, "FOTOCOPIAS")], [T(10, 502000, "Administración")], ReviewState(links={"1:10": "verified"})
    )
    assert [(x.line_id, x.ticket_id, x.status) for x in links] == [(1, 10, "verified")]


def test_unique_amount_alone_is_not_enough_for_auto():
    """Review L5: same amount but nothing else in common -> review, not auto."""
    [x] = match([L(1, 4321, "ABONO MENSUAL", sub="Seguros")], [T(10, 4321, "Kiosco", sub="Limpieza")])
    assert x.status == "pending"


def test_review_decisions_on_receipts_without_total_are_refused(data_dir, monkeypatch):
    """Review: matching ignores receipts without a total, so a decision on one would be lost."""
    from alas3 import review

    monkeypatch.setattr("alas3.ingest.load_manifests", lambda: [])
    monkeypatch.setattr("alas3.match.collect", lambda _m: ([], [T(5, 100, "x")], {}))
    with pytest.raises(ValueError, match="total"):
        review.apply({"type": "link", "line_id": 1, "ticket_id": 6, "decision": "verified"})
    review.apply({"type": "link", "line_id": 1, "ticket_id": 5, "decision": "verified"})
    review.apply({"type": "link", "line_id": 2, "ticket_id": 6, "decision": "rejected"})  # rejecting is fine
    with pytest.raises(ValueError, match="sin total"):
        review.edit_ticket(5, {"total": ""})
    assert review.load_review().links == {"1:5": "verified", "2:6": "rejected"}


def test_concurrent_review_decisions_are_all_kept(data_dir):
    """Review: the server is threaded; read-modify-write of review.json must not lose clicks."""
    from alas3 import review

    threads = [
        threading.Thread(
            target=review.apply,
            args=({"type": "payment", "line_id": i, "movement_id": 7, "decision": "verified"},),
        )
        for i in range(1, 31)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(review.load_review().payments) == 30


def test_rejecting_one_receipt_of_a_sum_keeps_the_others_proposed():
    line = LineRef(1, "2026-03", 600.0, "Mechas, lámparas, etc", None)
    tickets = [TicketRef(i, "2026-03", 200.0, f"Ferretería {i}", None) for i in (10, 11, 12)]
    assert {x.ticket_id for x in match([line], tickets)} == {10, 11, 12}  # a sum proposal
    # Without the kept pairs the sum breaks and every receipt drops out of the proposal.
    rejected_only = ReviewState(links={"1:10": "rejected"})
    assert not [x for x in match([line], tickets, rejected_only) if x.ticket_id in (11, 12)]
    review = ReviewState(links={"1:10": "rejected", "1:11": "pending", "1:12": "pending"})
    links = match([line], tickets, review)
    assert {(x.ticket_id, x.status) for x in links} == {(11, "pending"), (12, "pending")}
    # A kept receipt is not offered to another line while undecided.
    other = LineRef(2, "2026-03", 200.0, "Ferretería 11", None)
    assert all(x.line_id == 1 for x in match([line, other], tickets, review) if x.ticket_id in (11, 12))


def test_old_receipt_matches_a_line_of_its_bundle_month():
    line = LineRef(1, "2026-10", 11252.19, "Pinturería", None)
    old = TicketRef(5, "2026-07", 11252.19, "Colores Pinturerías", None, bundle_period="2026-10")
    assert [x.ticket_id for x in match([line], [old])] == [5]
    stray = TicketRef(6, "2026-10", 11252.19, "Colores Pinturerías", None, bundle_period="2026-07")
    assert match([line], [stray]) == []  # matching goes by the bundle, not by the receipt's date


def test_private_payroll_receipt_only_backs_its_own_category():
    """A payslip total read from a private page is never offered for an unrelated line of
    the same amount (it would be published as backing a plumbing job)."""
    from dataclasses import replace

    sub = "Sueldos y cargas sociales"
    priv = replace(T(1, 50000, "Recibo de sueldo (documento privado) sueldo neto", sub=sub), privado=True)
    plumbing = L(10, 50000, "MANO DE OBRA plomero", sub="Mantenimiento")
    assert match([plumbing], [priv]) == []
    salary = L(11, 50000, "SUELDO ENCARGADO mes 01/2026", sub=sub)
    assert [(x.line_id, x.ticket_id) for x in match([plumbing, salary], [priv])] == [(11, 1)]
