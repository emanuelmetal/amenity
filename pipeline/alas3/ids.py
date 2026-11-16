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
    Fiscal vouchers: document + point of sale + number. Others: document + first page +
    position on that page.
    """
    seen: Counter[tuple] = Counter()
    out: list[int] = []
    for t in tickets:
        if t.pto_vta is not None and t.nro_cmp is not None:
            key: tuple = ("v", sha16, t.pto_vta, t.nro_cmp)
        else:
            key = ("p", sha16, t.page_nos[0] if t.page_nos else 0)
        out.append(stable_id("ticket", *key, seen[key]))
        seen[key] += 1
    return out
