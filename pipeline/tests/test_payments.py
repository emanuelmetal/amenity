"""Cheques as payment evidence (payments.py): paired with the debit that cleared them."""

from alas3.payments import cheque_id, collect_payments
from alas3.schemas import BankMovement, BankStatement, Cheque, Comprobantes, DocumentManifest, PageRecord

R = "Banco Roela S.A."
REASON = "otro"


def _doc(i: int, period: str, n_pages: int, restricted: tuple[int, ...] = ()) -> DocumentManifest:
    return DocumentManifest(
        id=i, kind="comprobantes", period=period, title="t", source_name=f"c{i}.pdf", sha256=f"{i:02d}" * 32,
        pages=[PageRecord(page_no=n, restricted=n in restricted) for n in range(1, n_pages + 1)],
    )  # fmt: skip


def _cheque(numero: str, importe: float, pago: str, page: int) -> Cheque:
    return Cheque(numero=numero, banco=R, importe=importe, fecha_pago=pago, page=page)


def _setup(monkeypatch, exts: dict[int, Comprobantes]):
    monkeypatch.setattr("alas3.extract.load_extract", lambda m: exts[m.id])


def test_cleared_cheque_joins_its_debit_and_pending_one_stands_alone(monkeypatch):
    jul, sep = _doc(1, "2026-07", 20), _doc(2, "2026-09", 30)
    debit = BankMovement(fecha="2026-07-31", comprobante="9971847", codigo="149", descripcion="CHEQUE CAMARA RECIBIDA",
                         importe=1937061.4, page_nos=[24])  # fmt: skip
    st = BankStatement(banco=R, desde="2026-07-01", hasta="2026-07-31", saldo_inicial=0, saldo_final=0, creditos=0,
                       debitos=0, page_nos=[24], movements=[debit])  # fmt: skip
    exts = {
        1: Comprobantes(
            tickets=[],
            cheques=[
                _cheque("09971847", 1937061.4, "2026-07-30", 17),
                _cheque("09971848", 1937061.4, "2026-08-30", 17),
            ],
        ),  # fmt: skip
        # The next bundle shows the same photo again, plus the bank statement.
        2: Comprobantes(tickets=[], bank=[st], cheques=[_cheque("09971847", 1937061.4, "2026-07-30", 11)]),
    }
    _setup(monkeypatch, exts)
    pays = collect_payments([jul, sep])
    assert len(pays) == 2  # the debit (with cheque 47) and cheque 48 on its own; 47 never twice
    cleared, pending = pays
    assert cleared.mv.kind == "debito" and cleared.cheque.numero == "09971847"
    assert [(pm.id, n) for pm, n in cleared.pages] == [(2, 24), (1, 17)]  # statement, then the photo
    assert pending.mv.kind == "cheque" and pending.id == cheque_id(pending.cheque)
    assert (pending.mv.fecha, pending.mv.period, pending.m.id) == ("2026-08-30", "2026-08", 1)


def test_amount_mismatch_does_not_pair(monkeypatch):
    doc = _doc(1, "2026-07", 30)
    debit = BankMovement(fecha="2026-07-31", comprobante="9971847", descripcion="CHEQUE CAMARA RECIBIDA",
                         importe=1000.0, page_nos=[24])  # fmt: skip
    st = BankStatement(banco=R, desde="2026-07-01", hasta="2026-07-31", saldo_inicial=0, saldo_final=0, creditos=0,
                       debitos=0, page_nos=[24], movements=[debit])  # fmt: skip
    _setup(
        monkeypatch,
        {1: Comprobantes(tickets=[], bank=[st], cheques=[_cheque("09971847", 2000.0, "2026-07-30", 17)])},
    )
    debit_p, cheque_p = collect_payments([doc])
    assert debit_p.cheque is None and cheque_p.mv.kind == "cheque"


def test_publish_keeps_cheque_photo_and_skips_private_pages(monkeypatch):
    from alas3.publish import _bank_sql
    from alas3.schemas import ReviewState

    pub, priv = _doc(1, "2026-08", 20), _doc(2, "2026-08", 20, restricted=(5,))
    _setup(monkeypatch, {
        1: Comprobantes(tickets=[], cheques=[_cheque("09971848", 1937061.4, "2026-08-30", 17)]),
        2: Comprobantes(tickets=[], cheques=[_cheque("09971999", 500.0, "2026-08-30", 5)]),  # photo on a private page
    })  # fmt: skip
    sql = "\n".join(_bank_sql([pub, priv], [], ReviewState()))
    assert sql.count("INSERT INTO bank_movements") == 1
    assert "'cheque'" in sql and "'09971848'" in sql and "'2026-08-30'" in sql
    assert "09971999" not in sql


def test_decision_on_a_cheque_moves_to_the_debit_that_cleared_it(monkeypatch):
    from alas3.payments import cheque_aliases
    from alas3.review import carry_cheque_decisions
    from alas3.schemas import ReviewNote, ReviewState

    sep, oct_ = _doc(1, "2026-09", 20), _doc(2, "2026-10", 30)
    chq = _cheque("09971850", 1845730.0, "2026-10-10", 17)
    # The September bundle has the photo only: the cheque is a payment of its own.
    exts = {1: Comprobantes(tickets=[], cheques=[chq])}
    _setup(monkeypatch, exts)
    (alone,) = collect_payments([sep])
    assert cheque_aliases([alone]) == {}
    state = ReviewState(payments={f"7:{alone.id}": "verified", f"8:{alone.id}": "rejected"},
                        notes={f"payment:8:{alone.id}": ReviewNote(motivo=REASON, fecha="2026-10-01")})  # fmt: skip
    # Then the October statement shows it cleared: same cheque, now inside a debit.
    debit = BankMovement(fecha="2026-10-13", comprobante="9971850", codigo="149", descripcion="CHEQUE CAMARA RECIBIDA",
                         importe=1845730.0, page_nos=[24])  # fmt: skip
    st = BankStatement(banco=R, desde="2026-10-01", hasta="2026-10-31", saldo_inicial=0, saldo_final=0, creditos=0,
                       debitos=0, page_nos=[24], movements=[debit])  # fmt: skip
    exts[2] = Comprobantes(tickets=[], bank=[st])
    (cleared,) = collect_payments([sep, oct_])
    assert cleared.cheque.numero == "09971850" and cleared.id != alone.id
    aliases = cheque_aliases([cleared])
    assert aliases == {alone.id: cleared.id}
    state.payments[f"9:{alone.id}"] = "verified"
    state.payments[f"9:{cleared.id}"] = "rejected"  # decided on the debit itself: that one wins
    moved = carry_cheque_decisions(state, aliases)
    assert state.payments == {f"7:{cleared.id}": "verified", f"8:{cleared.id}": "rejected", f"9:{cleared.id}": "rejected"}
    assert list(state.notes) == [f"payment:8:{cleared.id}"] and len(moved) == 2
    assert carry_cheque_decisions(state, aliases) == []  # idempotent


def test_cheque_is_proposed_for_an_earlier_line():
    from alas3.match import CHEQUE_MONTHS_AFTER, LineRef, TicketRef, match_payments

    line = LineRef(1, "2026-08", 1937061.4, "Impermeabilización terraza", None)
    cheque = TicketRef(10, "2026-09", 1937061.4, "CHEQUE CAMARA RECIBIDA", None, months_after=CHEQUE_MONTHS_AFTER)
    transfer = TicketRef(11, "2026-09", 1937061.4, "TRANSF.INTERB", None)
    (link,) = match_payments([line], [cheque, transfer])
    assert (link.ticket_id, link.status) == (10, "pending")  # a proposal, for a person to confirm
    too_late = TicketRef(12, "2026-12", 1937061.4, "CHEQUE CAMARA RECIBIDA", None, months_after=CHEQUE_MONTHS_AFTER)
    assert match_payments([line], [too_late]) == []
    assert match_payments([line], [transfer]) == []  # other debits: never after the line's month


def test_equal_cheques_go_to_the_closest_month():
    from alas3.match import CHEQUE_MONTHS_AFTER, LineRef, TicketRef, match_payments

    jul = LineRef(1, "2026-07", 1937061.4, "Impermeabilización terraza", None)
    aug = LineRef(2, "2026-08", 1937061.4, "Impermeabilización terraza", None)
    c47 = TicketRef(10, "2026-07", 1937061.4, "CHEQUE CAMARA RECIBIDA", None, months_after=CHEQUE_MONTHS_AFTER)
    c48 = TicketRef(11, "2026-09", 1937061.4, "CHEQUE CAMARA RECIBIDA", None, months_after=CHEQUE_MONTHS_AFTER)
    links = match_payments([jul, aug], [c48, c47])
    assert sorted((x.line_id, x.ticket_id) for x in links) == [(1, 10), (2, 11)]


def test_pending_cheque_description_never_names_the_beneficiary(monkeypatch):
    """Who a cheque pays (often a person) helps matching but is never published."""
    doc = _doc(1, "2026-07", 20)
    chq = Cheque(numero="00001234", banco=R, importe=5000.0, fecha_pago="2026-08-02", page=3,
                 beneficiario="Persona Inventada")  # fmt: skip
    _setup(monkeypatch, {1: Comprobantes(tickets=[], cheques=[chq])})
    (p,) = collect_payments([doc])
    assert p.mv.kind == "cheque" and "Persona" not in p.mv.descripcion and "00001234" in p.mv.descripcion
