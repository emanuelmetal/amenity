"""Payment evidence: bank debits of the statements, and the cheques the consortium issued.

A cheque photographed in a receipts bundle (TicketTranscription.cheques) is paired with
the debit that cleared it: Banco Roela writes "CHEQUE CAMARA RECIBIDA" with the cheque
number as voucher. The debit keeps its id (review decisions point at it) and gains the
cheque's photo. A cheque no statement shows cleared yet (a later payment date, or a
statement not uploaded) is a payment on its own (kind 'cheque'), so it is never counted
twice. Bundles repeat photos (the July cheques again in August): one cheque per number.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ids import movement_ids, stable_id
from .schemas import BankMovement, Cheque, DocumentManifest

CENT = 0.01


@dataclass
class Payment:
    id: int
    m: DocumentManifest  # document of the debit, or of the cheque when it has not cleared
    mv: BankMovement
    banco: str | None
    pages: list[tuple[DocumentManifest, int]]  # the statement page(s), then the cheque photo
    cheque: Cheque | None = None


def cheque_id(c: Cheque) -> int:
    return stable_id("cheque", c.banco.lower(), c.key)


def collect_payments(manifests: list[DocumentManifest]) -> list[Payment]:
    from .config import PHASE_KINDS
    from .extract import load_extract
    from .schemas import Comprobantes

    debits: list[Payment] = []
    cheques: dict[str, tuple[DocumentManifest, Cheque]] = {}
    for m in manifests:
        if m.kind not in PHASE_KINDS:
            continue
        ext = load_extract(m)
        if not isinstance(ext, Comprobantes):
            continue
        for st in ext.bank:
            for mid, mv in zip(movement_ids(m.work_dir_name, st.movements), st.movements, strict=True):
                debits.append(Payment(mid, m, mv, st.banco, [(m, n) for n in mv.page_nos]))
        for c in ext.cheques:
            cheques.setdefault(c.key, (m, c))  # first bundle that shows it

    cleared: set[str] = set()
    for p in debits:
        if p.mv.kind != "debito" or "CHEQUE" not in p.mv.descripcion.upper() or not p.mv.comprobante:
            continue
        hit = cheques.get(p.mv.comprobante.lstrip("0"))
        if hit and hit[1].key not in cleared and abs(hit[1].importe - p.mv.importe) <= CENT:
            cm, c = hit
            p.cheque = c
            p.pages.append((cm, c.page))
            cleared.add(c.key)

    pending: list[Payment] = []
    for key, (cm, c) in sorted(cheques.items()):
        if key in cleared:
            continue
        # The beneficiary is often a person (the encargado, an owner): it is used for matching
        # (collect_movements) but never published in the description.
        mv = BankMovement(fecha=c.fecha_pago, comprobante=c.numero, descripcion=f"Cheque de pago diferido N° {c.numero}",
                          importe=c.importe, kind="cheque", page_nos=[c.page])  # fmt: skip
        pending.append(Payment(cheque_id(c), cm, mv, c.banco, [(cm, c.page)], c))
    return debits + pending


def cheque_aliases(payments: list[Payment]) -> dict[int, int]:
    """Cheque id -> id of the debit that cleared it. A cheque is linked by its own id while
    no statement shows it; once one does, it becomes part of that debit (the id changes)."""
    return {cheque_id(p.cheque): p.id for p in payments if p.cheque is not None and p.mv.kind != "cheque"}
