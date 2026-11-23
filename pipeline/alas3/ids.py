"""Stable ids for records that are re-extracted on every run.

Links (expense line <-> ticket) and review decisions refer to these ids, so they
must not change when a document is re-ingested. 52-bit integers: exact in
JavaScript numbers and SQLite INTEGER.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from .schemas import Liquidacion


def stable_id(*parts: object) -> int:
    key = "\x1f".join("" if p is None else str(p) for p in parts)
    return int(hashlib.sha256(key.encode()).hexdigest()[:13], 16)


def expense_line_ids(liq: Liquidacion) -> list[int]:
    """One id per line, in order. Identical lines get an occurrence number."""
    seen: Counter[tuple] = Counter()
    out: list[int] = []
    for ln in liq.lines:
        key = (liq.period, ln.concepto, ln.detalle, f"{ln.importe:.2f}")
        if ln.fondo:  # its own namespace, so the ids of ordinary lines never change
            key = ("fondo", *key)
        out.append(stable_id("line", *key, seen[key]))
        seen[key] += 1
    return out


def movement_ids(sha16: str, movements: list) -> list[int]:
    """Stable bank movement ids: document + date + bank voucher + concept + amount. The
    grouped charges of a statement: document + date (one per statement)."""
    seen: Counter[tuple] = Counter()
    out: list[int] = []
    for mv in movements:
        if mv.kind == "gastos":
            key: tuple = ("gastos", sha16, mv.fecha)
        else:
            key = ("mov", sha16, mv.fecha, mv.comprobante, mv.codigo, f"{mv.importe:.2f}")
        out.append(stable_id("movement", *key, seen[key]))
        seen[key] += 1
    return out


def ticket_ids(sha16: str, tickets: list) -> list[int]:
    """Stable receipt ids, built only from where the receipt is: never from its CUIT (a
    person's CUIL for monotributo vendors could be brute-forced back out of the published
    id) nor from fields a reviewer can edit (total), so decisions in review.json survive.
    Fiscal vouchers: document + point of sale + number + first page (two small vendors in
    one bundle can share point of sale 1 / number 123; the voucher type is left out because
    it is missing when a QR stops decoding). Others: document + first page + position on
    that page. Private payroll receipts (several concepts on one payslip page): document +
    page + concept + month, so reordering `private_receipts` never swaps their ids.
    """
    seen: Counter[tuple] = Counter()
    out: list[int] = []
    for t in tickets:
        if getattr(t, "privado", False):
            key: tuple = ("priv", sha16, t.page_nos[0] if t.page_nos else 0, t.descripcion, t.period)
        elif t.pto_vta is not None and t.nro_cmp is not None:
            key = ("v", sha16, t.pto_vta, t.nro_cmp, min(t.page_nos) if t.page_nos else 0)
        else:
            key = ("p", sha16, t.page_nos[0] if t.page_nos else 0)
        out.append(stable_id("ticket", *key, seen[key]))
        seen[key] += 1
    return out


def article_ids(sha16: str, articles: list) -> list[int]:
    """Reglamento articles (comments point at them): document + article number + occurrence."""
    seen: Counter[str] = Counter()
    out: list[int] = []
    for a in articles:
        out.append(stable_id("article", sha16, a.numero, seen[a.numero]))
        seen[a.numero] += 1
    return out


def acta_id(acta) -> int:
    """By the acta's number in the book (or its date when it has none)."""
    return stable_id("acta", acta.key)


def acta_item_ids(acta) -> list[int]:
    """Position within the acta: rewording an item keeps its id."""
    return [stable_id("acta_item", acta.key, i) for i in range(len(acta.items))]
