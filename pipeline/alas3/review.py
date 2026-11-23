"""Step 9: local review (`make review`), PLAN.md §4.9.

A tiny stdlib HTTP server on 127.0.0.1 with one page (review/index.html). It shows:
- links waiting for a decision (sums, ties, near amounts) and automatic ones;
- every receipt, with editable fields, and every bank movement;
- by month, every expense line next to the receipts and bank movements;
and lets any receipt, or any debit of a bank statement (bank.py), be linked to any
line by hand (a 'verified' decision), starting from the line or from a receipt.
Everything of a month stays listed, linked or not, until the reviewer closes the month
(ReviewState.closed_months; reopening shows it again).

Decisions go to data/work/review.json (schemas.ReviewState) and edits of receipt
fields to the transcription file (data/work/extract/<sha16>.tickets.json); the next
`make publish` applies them. Nothing here touches the live site.

Pages are shown as the redacted renders (pNNN.webp, made from public.pdf); "Ver original"
renders one page from the inbox PDF without blackouts so the reviewer can read what a
blackout covers (never stored or published; never for a restricted page). A private
receipt (payroll page) shows only its amount/period boxes (PrivateReceipt.crops), cropped
on the fly. The server
binds to 127.0.0.1, checks the Host header (DNS rebinding) and requires a custom
header on every POST (so other web pages cannot submit decisions).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import WORK
from .schemas import REJECT_REASONS, AcceptedDiff, ReviewNote, ReviewState

REVIEW_FILE = WORK / "review.json"
PAGE = Path(__file__).parent / "review" / "index.html"
EDITABLE = {"proveedor", "descripcion", "fecha", "total", "kind"}


def load_review() -> ReviewState:
    if not REVIEW_FILE.exists():
        return ReviewState()
    return ReviewState.model_validate_json(REVIEW_FILE.read_text())  # fails loudly on bad input


def save_review(state: ReviewState) -> None:
    REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REVIEW_FILE.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=1))
    tmp.replace(REVIEW_FILE)


def carry_cheque_decisions(state: ReviewState, aliases: dict[int, int]) -> list[str]:
    """Moves decisions (and rejection notes) made on a cheque not cleared yet to the debit that
    cleared it, so a confirmed link survives the bank statement arriving. A decision already
    made on the debit itself wins. Returns what moved."""
    moved = []
    for key in [k for k in state.payments if int(k.split(":")[1]) in aliases]:
        lid, cid = key.split(":")
        new = f"{lid}:{aliases[int(cid)]}"
        decision = state.payments.pop(key)
        if new not in state.payments:
            state.payments[new] = decision
            moved.append(f"{key} -> {new} ({decision})")
        note = state.notes.pop(f"payment:{key}", None)
        if note is not None:
            state.notes.setdefault(f"payment:{new}", note)
    return moved


def sync_cheque_decisions(mlookup: dict) -> ReviewState:
    """load_review(), with decisions on cleared cheques moved to their debit (and saved)."""
    from .payments import cheque_aliases

    state = load_review()
    moved = carry_cheque_decisions(state, cheque_aliases(list(mlookup.values())))
    if moved:
        save_review(state)
        for x in moved:
            print(f"cheque cleared, decision moved to its bank debit: {x}")
    return state


def _pages(m, page_nos: list[int]) -> list[dict]:
    restricted = {p.page_no for p in m.pages if p.restricted}
    return [{"doc": m.work_dir_name, "page": n} for n in page_nos if n not in restricted]


def line_coverage(
    lines,
    links,
    pay_links,
    ticket_total: dict[int, float],
    movement_total: dict[int, float],
    receipt_periods: set | None = None,
    payment_periods: set | None = None,
    self_proving: set[int] | None = None,
    accepted: dict[str, float] | None = None,
) -> dict[int, dict]:
    """How much of each expense line its receipts, and separately its bank payments, cover.

    A line needs both: a receipt (what was bought) and a bank payment (that it was paid).
    Each side is only required in the months that have that evidence (`*_periods`; None =
    every month): receipts of the month or the one before; for a payment, the bank statement
    of the line's own month (no Banco Roela statement for a month = no payment asked for).

    Per side, `covered` counts confirmed and automatic links and `proposed` the ones still
    waiting for a decision. A receipt or payment linked to several lines (one receipt for
    honorarios + fotocopias) adds at most the line's amount to each and is flagged `shared`.
    Payments in `self_proving` (the month's grouped bank charges: the statement itself is
    the voucher) count for the receipt side too.
    `accepted` ("<line_id>:receipt|payment" -> amount): a difference the reviewer accepted;
    that side is settled while what is missing stays within it.
    """
    from .match import CENT, _prev

    importe = {ln.id: ln.importe for ln in lines}
    period = {ln.id: ln.period for ln in lines}

    # Receipts of the line's month or the one before can back it (match.py); a payment is only
    # asked for when the bank statement of the line's own month was uploaded.
    def has(kind: str, periods: set | None, p: str) -> bool:
        return periods is None or p in periods or (kind == "ticket" and _prev(p) in periods)

    linked = [("ticket", x, ticket_total) for x in links] + [
        ("payment", x, movement_total) for x in pay_links
    ]
    n_lines: dict[tuple[str, int], int] = {}
    for kind, x, _ in linked:
        n_lines[(kind, x.ticket_id)] = n_lines.get((kind, x.ticket_id), 0) + 1
    sides = {"ticket": receipt_periods, "payment": payment_periods}
    out = {
        ln.id: {"items": [], **{k: {"covered": 0.0, "proposed": 0.0, "pending": False} for k in sides}}
        for ln in lines
    }
    for kind, x, totals in linked:
        if x.line_id not in out or x.ticket_id not in totals:
            continue
        total = totals[x.ticket_id]
        shared = n_lines[(kind, x.ticket_id)]
        part = min(total, importe[x.line_id]) if shared > 1 else total
        for side_kind in [kind] + (
            ["ticket"] if kind == "payment" and x.ticket_id in (self_proving or ()) else []
        ):
            side = out[x.line_id][side_kind]
            side["proposed" if x.status == "pending" else "covered"] += part
            side["pending"] |= x.status == "pending"
        out[x.line_id]["items"].append(
            {"type": kind, "id": x.ticket_id, "status": x.status, "shared": shared}
        )
    side_name = {"ticket": "receipt", "payment": "payment"}
    for lid, cov in out.items():
        for kind, periods in sides.items():
            side = cov[kind]
            side["covered"] = round(min(side["covered"], importe[lid]), 2)
            side["proposed"] = round(side["proposed"], 2)
            side["remaining"] = round(importe[lid] - side["covered"], 2)
            ok = (accepted or {}).get(f"{lid}:{side_name[kind]}")
            # Only with something linked: an accepted difference never stands for the evidence.
            side["accepted"] = ok if ok and side["covered"] > 0 and side["remaining"] > CENT else None
            side["settled"] = side["remaining"] <= CENT or (
                side["accepted"] is not None and side["remaining"] <= ok + CENT
            )
            side["needed"] = has(kind, periods, period[lid]) or side["covered"] > 0 or side["proposed"] > 0
        # Missing (and not waiting in "Para revisar"): what keeps the line uncovered in "Por mes".
        cov["missing"] = [
            k for k in sides if cov[k]["needed"] and not cov[k]["settled"] and not cov[k]["pending"]
        ]
        cov["settled"] = all(cov[k]["settled"] for k in sides if cov[k]["needed"])
    return out


def queue() -> dict:
    from .ingest import load_manifests
    from .match import collect, collect_movements, match, match_payments

    manifests = load_manifests()
    movements, mlookup = collect_movements(manifests)
    state = sync_cheque_decisions(mlookup)
    lines, tickets, lookup = collect(manifests)
    links = match(lines, tickets, state)
    decided = state.links
    pay_links = match_payments(lines, movements, state)

    cover = line_coverage(
        lines, links, pay_links, {t.id: t.total for t in tickets}, {mv.id: mv.total for mv in movements},
        receipt_periods={t.bundle_period or t.period for t in tickets}, payment_periods={mv.period for mv in movements if mlookup[mv.id].mv.kind != "cheque"},
        self_proving={mid for mid, p in mlookup.items() if p.mv.kind == "gastos"},
        accepted={k: v.importe for k, v in state.accepted_diffs.items()},
    )  # fmt: skip

    def line_json(lid: int) -> dict:
        m, ln = lookup["lines"][lid]
        cov = cover[lid]
        items = [
            {
                **(ticket_json(i["id"]) if i["type"] == "ticket" else movement_json(i["id"])),
                "type": i["type"],
                "status": i["status"],
                "shared": i["shared"],
            }
            for i in cov["items"]
        ]
        return {"id": str(lid), "period": m.period, "rubro": ln.rubro, "concepto": ln.concepto, "detalle": ln.detalle,
                "importe": ln.importe, "verified": lid in state.lines_verified, "pages": _pages(m, [ln.page_no or 1]),
                "receipt": cov["ticket"], "payment": cov["payment"], "settled": cov["settled"],
                "missing": cov["missing"], "items": items}  # fmt: skip

    tickets_by_id = {t.id: t for t in tickets}
    # Which lines each receipt / bank movement is linked to (any status), so the page can
    # keep showing linked items of open months with where they went.
    linked_to: dict[tuple[str, int], list[dict]] = {}
    for kind, ls in (("ticket", links), ("payment", pay_links)):
        for x in ls:
            lm, ln = lookup["lines"][x.line_id]
            linked_to.setdefault((kind, x.ticket_id), []).append(
                {"line_id": str(x.line_id), "period": lm.period, "concepto": ln.concepto, "status": x.status}
            )

    def ticket_json(tid: int) -> dict:
        m, t = lookup["tickets"][tid]
        return {"id": str(tid), "period": getattr(tickets_by_id.get(tid), "period", None), "bundle_period": m.period, "kind": t.kind, "letra": t.letra, "fecha": t.fecha, "proveedor": t.proveedor,
                "descripcion": t.descripcion, "total": t.total, "source": t.source, "confidence": t.confidence,
                "verified": t.verified or tid in state.tickets_verified, "pages": _pages(m, t.page_nos),
                "privado": t.privado, "crops": _private_crops(m, t),
                "linked_to": linked_to.get(("ticket", tid), [])}  # fmt: skip

    def movement_json(mid: int) -> dict:
        # Same shape as a receipt, so the page shows both with the same cards. A cleared
        # cheque shows the statement page, then the cheque's photo.
        p = mlookup[mid]
        mv, c = p.mv, p.cheque
        detail = "; ".join(f"{i.descripcion} ×{i.cantidad}: ${i.importe:,.2f}" for i in mv.items) or None
        if c is not None:
            detail = f"Cheque N° {c.numero} del {c.banco}, pagadero el {c.fecha_pago}" + (
                " (todavía no figura debitado en un resumen)"
                if mv.kind == "cheque"
                else f", debitado el {mv.fecha}"
            )
        kind = {"gastos": "gastos bancarios", "cheque": "cheque sin debitar"}.get(
            mv.kind, "cheque debitado" if c else "pago bancario"
        )
        pages = [pg for pm, n in p.pages for pg in _pages(pm, [n])]
        return {"id": str(mid), "type": "payment", "kind": kind,
                "letra": None, "fecha": mv.fecha, "period": mv.period, "proveedor": mv.descripcion, "descripcion": detail,
                "total": mv.importe, "source": "banco", "confidence": 1.0, "verified": True, "pages": pages,
                "linked_to": linked_to.get(("payment", mid), [])}  # fmt: skip

    groups = []
    for kind, ls_all, as_json, decisions in (
        ("ticket", links, ticket_json, decided),
        ("payment", pay_links, movement_json, state.payments),
    ):
        by_line: dict[int, list] = {}
        for ln in ls_all:
            by_line.setdefault(ln.line_id, []).append(ln)
        for lid, ls in by_line.items():
            groups.append({
                "type": kind,
                "line": line_json(lid),
                "tickets": [as_json(x.ticket_id) for x in ls],
                "score": min(x.score for x in ls),
                "status": "verified" if all(x.status == "verified" for x in ls) else ("auto" if all(x.status == "auto" for x in ls) else "pending"),
                "reason": ls[0].reason,
                "decisions": {str(x.ticket_id): decisions.get(f"{lid}:{x.ticket_id}") for x in ls},
            })  # fmt: skip
    groups.sort(
        key=lambda g: (
            {"pending": 0, "auto": 1, "verified": 2}[g["status"]],
            g["line"]["period"],
            -g["line"]["importe"],
        )
    )
    linked_lines = {x.line_id for x in links} | {x.line_id for x in pay_links}
    linked_tickets = {x.ticket_id for x in links}
    linked_movements = {x.ticket_id for x in pay_links}
    months = month_status(
        lines, cover, tickets, movements, linked_tickets, linked_movements,
        verified={t.id for t in tickets if lookup["tickets"][t.id][1].verified or t.id in state.tickets_verified},
        closed=set(state.closed_months),
    )  # fmt: skip
    return {
        "months": months,
        "groups": groups,
        # Every receipt, line and bank movement, linked or not: the page shows all of an open
        # month and hides a month only once the reviewer closes it (closed_months), so nothing
        # leaves the screen while that month is still being reviewed.
        "receipts": [{**ticket_json(t.id), "type": "ticket", "linked": t.id in linked_tickets}
                     for t in sorted(tickets, key=lambda x: (x.period or "", x.text))],  # fmt: skip
        "closed_months": sorted(state.closed_months),
        "periods": sorted({ln.period for ln in lines}),
        # Everything, for linking by hand from the page (any receipt to any line).
        "all_receipts": [
            {"id": str(t.id), "period": t.period, "bundle_period": t.bundle_period, "total": t.total, "text": t.text,
             "proveedor": lookup["tickets"][t.id][1].proveedor, "descripcion": lookup["tickets"][t.id][1].descripcion,
             "kind": lookup["tickets"][t.id][1].kind, "fecha": lookup["tickets"][t.id][1].fecha,
             "pages": _pages(lookup["tickets"][t.id][0], lookup["tickets"][t.id][1].page_nos),
             "linked": t.id in linked_tickets}
            for t in sorted(tickets, key=lambda x: (x.period or "", x.text))
        ],  # fmt: skip
        "all_lines": [
            {**line_json(ln.id), "linked": ln.id in linked_lines}
            for ln in sorted(lines, key=lambda x: (x.period or "", -x.importe))
        ],
        "all_movements": [
            {**movement_json(mv.id), "linked": mv.id in linked_movements}
            for mv in sorted(movements, key=lambda x: (x.period or "", -x.total))
        ],
        "rejected": len(state.rejected_pairs()) + sum(1 for v in state.payments.values() if v == "rejected"),
        "reject_reasons": list(REJECT_REASONS),
        "rejections": rejections(state, line_json, ticket_json, movement_json, lookup, mlookup),
        "actas": actas_json(state, lookup["lines"]),
    }  # fmt: skip


def actas_json(state: ReviewState, lines: dict) -> list[dict]:
    """The transcribed actas (actas.py) next to their folio photos, for the owner to check the
    transcription and the gastos it links to (`actas_verified`)."""
    from .actas import load_book

    book = load_book()
    out = []
    for a in sorted(book.actas, key=lambda a: a.fecha):
        items = []
        for it in a.items:
            gastos = []
            for lid in it.gastos:
                if lid in lines:
                    m, ln = lines[lid]
                    gastos.append({"id": str(lid), "period": m.period, "concepto": ln.concepto, "detalle": ln.detalle,
                                   "importe": ln.importe})  # fmt: skip
                else:
                    gastos.append({"id": str(lid), "missing": True})
            items.append({**it.model_dump(exclude={"gastos"}), "gastos": gastos})
        out.append({
            "key": a.key, "numero": a.numero, "fecha": a.fecha, "tipo": a.tipo, "resumen": a.resumen,
            "asistentes": a.asistentes, "items": items, "verified": a.verified or a.key in state.actas_verified,
            "folios": [{"doc": k.split("#")[0], "page": int(k.split("#")[1]) if "#" in k else 1,
                        "folio": book.folios[k].folio, "texto": book.folios[k].texto} for k in a.folios],
        })  # fmt: skip
    return out


def month_status(
    lines, cover, tickets, movements, linked_tickets, linked_movements, verified: set[int], closed: set[str]
) -> list[dict]:
    """Per month: what is still open and whether it can be closed (nothing open at all).

    A month counts a line by its period, a receipt by its own month (else its bundle's) and a
    bank movement by its period. Open = a line not covered on a side it needs (an accepted
    difference counts as covered), a proposal waiting in "Para revisar", a receipt not
    verified or not linked to any line, a bank movement not linked to any line.
    """
    m: dict[str, dict] = {}

    def row(p: str) -> dict:
        return m.setdefault(p, {"period": p, "lines": 0, "covered": 0, "pending": 0, "receipts": 0,
                                "receipts_free": 0, "unverified": 0, "movements": 0, "movements_free": 0})  # fmt: skip

    for ln in lines:
        r, cov = row(ln.period), cover[ln.id]
        r["lines"] += 1
        r["covered"] += cov["settled"]
        r["pending"] += cov["ticket"]["pending"] or cov["payment"]["pending"]
    for t in tickets:
        if not (t.period or t.bundle_period):
            continue
        r = row(t.period or t.bundle_period)
        r["receipts"] += 1
        r["receipts_free"] += t.id not in linked_tickets
        r["unverified"] += t.id not in verified
    for mv in movements:
        r = row(mv.period)
        r["movements"] += 1
        r["movements_free"] += mv.id not in linked_movements
    out = []
    for p in sorted(m, reverse=True):
        r = m[p]
        blockers = [
            f"{n} {what}"
            for n, what in (
                (r["lines"] - r["covered"], "gastos sin cubrir"),
                (r["pending"], "gastos con propuestas para revisar"),
                (r["receipts_free"], "comprobantes sin gasto"),
                (r["unverified"], "comprobantes sin verificar"),
                (r["movements_free"], "movimientos sin gasto"),
            )
            if n
        ]
        out.append({**r, "blockers": blockers, "ready": not blockers, "closed": p in closed})
    return out


def rejections(
    state: ReviewState, line_json, ticket_json, movement_json, lookup: dict, mlookup: dict
) -> list[dict]:
    """Every rejected link with its line, receipt or payment, and the reason (if one was given)."""
    out = []
    for kind, decisions, exists in (
        ("link", state.links, lambda i: i in lookup["tickets"]),
        ("payment", state.payments, lambda i: i in mlookup),
    ):
        for key, v in decisions.items():
            if v != "rejected":
                continue
            lid, oid = map(int, key.split(":"))
            if lid not in lookup["lines"] or not exists(oid):
                continue  # dangling: `alas3 validate` reports it
            note = state.notes.get(f"{kind}:{key}")
            other = ticket_json(oid) if kind == "link" else movement_json(oid)
            out.append({"kind": kind, "line": line_json(lid), "item": {**other, "type": "payment" if kind == "payment" else "ticket"},
                        "note": note.model_dump() if note else None})  # fmt: skip
    out.sort(
        key=lambda r: (r["note"] is not None, r["note"]["fecha"] if r["note"] else "", r["line"]["period"]),
        reverse=True,
    )
    return out


_LOCK = threading.Lock()  # ThreadingHTTPServer: two quick clicks must not lose a decision


def apply(action: dict) -> None:
    """One decision from the page (serialised: each one reads, changes and writes files)."""
    with _LOCK:
        _apply(action)


def _apply(action: dict) -> None:
    state = load_review()
    kind = action.get("type")
    if kind == "link" and action.get("decision") == "verified":
        _require_total(int(action["ticket_id"]))
    if kind in ("link", "payment"):
        other = int(action["ticket_id"] if kind == "link" else action["movement_id"])
        key = f"{int(action['line_id'])}:{other}"
        decisions = state.links if kind == "link" else state.payments
        decision = action.get("decision")
        if decision in ("verified", "rejected", "pending"):
            decisions[key] = decision
        else:
            decisions.pop(key, None)
        # Rejecting one receipt of a proposal keeps the others proposed (unless decided).
        if decision == "rejected":
            for kid in action.get("keep") or []:
                decisions.setdefault(f"{int(action['line_id'])}:{int(kid)}", "pending")
        # Why it was rejected, for whoever fixes the data (`alas3 review-notes`).
        if decision == "rejected" and action.get("motivo"):
            state.notes[f"{kind}:{key}"] = ReviewNote(
                motivo=action["motivo"],
                detalle=str(action.get("detalle") or "").strip(),
                fecha=date.today().isoformat(),
            )
        elif decision != "rejected":
            state.notes.pop(f"{kind}:{key}", None)
    elif kind in ("ticket", "line"):
        target = state.tickets_verified if kind == "ticket" else state.lines_verified
        eid = int(action["id"])
        if action.get("verified") and eid not in target:
            target.append(eid)
        elif not action.get("verified") and eid in target:
            target.remove(eid)
    elif kind == "accept_diff":
        side = action.get("side")
        if side not in ("receipt", "payment"):
            raise ValueError(f"bad side {side!r}")
        key = f"{int(action['line_id'])}:{side}"
        if action.get("importe") is None:
            state.accepted_diffs.pop(key, None)
        else:
            state.accepted_diffs[key] = AcceptedDiff(
                importe=round(float(action["importe"]), 2),
                detalle=str(action.get("detalle") or "").strip(),
                fecha=date.today().isoformat(),
            )
    elif kind == "month":
        period = str(action.get("period") or "")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise ValueError(f"bad period {period!r}")
        if action.get("closed") and period not in state.closed_months:
            # Only a month with nothing open (month_status); reopening is always allowed.
            row = next((r for r in queue()["months"] if r["period"] == period), None)
            if row and row["blockers"]:
                raise ValueError(f"{period} todavía tiene " + ", ".join(row["blockers"]))
            state.closed_months = sorted([*state.closed_months, period])
        elif not action.get("closed") and period in state.closed_months:
            state.closed_months.remove(period)
    elif kind == "acta":
        from .actas import load_book

        key = str(action.get("key") or "")
        if key not in {a.key for a in load_book().actas}:
            raise ValueError(f"unknown acta {key!r}")
        if action.get("verified") and key not in state.actas_verified:
            state.actas_verified.append(key)
        elif not action.get("verified") and key in state.actas_verified:
            state.actas_verified.remove(key)
    elif kind == "edit":
        edit_ticket(int(action["id"]), {k: v for k, v in action.get("fields", {}).items() if k in EDITABLE})
        return
    else:
        raise ValueError(f"unknown action {kind!r}")
    save_review(state)


def _linked(tid: int) -> bool:
    return any(k.split(":")[1] == str(tid) and v == "verified" for k, v in load_review().links.items())


def _require_total(tid: int) -> None:
    """Matching ignores receipts without a total, so a decision on one would be lost silently."""
    from .ingest import load_manifests
    from .match import collect

    _, tickets, _ = collect(load_manifests())
    if tid not in {t.id for t in tickets}:
        raise ValueError("Cargá el total del comprobante antes de vincularlo")


def edit_ticket(tid: int, fields: dict) -> None:
    """Writes corrected fields into the transcription file, then re-extracts that document."""
    import math

    from .extract import extract_document
    from .ids import ticket_ids
    from .ingest import load_manifests
    from .match import collect
    from .receipts import build_with_origin, load_transcription, transcription_path
    from .schemas import Ticket

    if "total" in fields and fields["total"] in (None, "") and _linked(tid):
        raise ValueError("El comprobante está vinculado a un gasto: no se puede dejar sin total")
    _, _, lookup = collect(load_manifests())
    m, _ = lookup["tickets"][tid]
    comp, origin = build_with_origin(m)
    pos = ticket_ids(m.work_dir_name, comp.tickets).index(tid)  # the exact receipt, not a look-alike
    built = comp.tickets[pos]
    if built.privado:
        raise ValueError(
            "Comprobante privado (página de sueldos): se corrige en private_receipts del archivo de transcripción"
        )
    tr = load_transcription(m)
    if origin[pos] is not None:
        entry = tr.tickets[origin[pos]]
    else:  # a QR-only receipt: start a transcription entry for it
        entry = Ticket(
            page_nos=built.page_nos, tipo_cmp=built.tipo_cmp, pto_vta=built.pto_vta, nro_cmp=built.nro_cmp
        )
        tr.tickets.append(entry)
    for k, v in fields.items():
        if k == "total":
            v = float(v) if v not in (None, "") else None
            if v is not None and not math.isfinite(v):
                raise ValueError("total must be a finite number")
        setattr(entry, k, v if v != "" else None)
    Ticket.model_validate(entry.model_dump())  # same rules as a hand-written file
    path = transcription_path(m)
    path.write_text(tr.model_dump_json(indent=1, exclude_defaults=True))
    extract_document(m)


def dangling_decisions() -> list[str]:
    """Decisions in review.json that point at lines or receipts that no longer exist."""
    from .ingest import load_manifests
    from .match import collect, collect_movements

    manifests = load_manifests()
    movements, mlookup = collect_movements(manifests)
    # Decisions on a cheque a statement now shows cleared move to its debit first; otherwise
    # they would be reported as dangling although `make review` would carry them over.
    state = sync_cheque_decisions(mlookup)
    lines, tickets, _ = collect(manifests)
    mids = {mv.id for mv in movements}
    lids, tids = {ln.id for ln in lines}, {t.id for t in tickets}
    out = [
        f"link {k} ({v})"
        for k, v in state.links.items()
        if int(k.split(":")[0]) not in lids or int(k.split(":")[1]) not in tids
    ]
    out += [f"verified receipt {t}" for t in state.tickets_verified if t not in tids]
    out += [f"verified line {ln}" for ln in state.lines_verified if ln not in lids]
    out += [
        f"payment {k} ({v})"
        for k, v in state.payments.items()
        if int(k.split(":")[0]) not in lids or int(k.split(":")[1]) not in mids
    ]
    return out


def _image(doc: str, page: int) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{16}", doc):
        return None
    p = WORK / "docs" / doc / f"p{page:03d}.webp"  # redacted render; restricted pages have none
    return p if p.exists() else None


_SOURCES: dict[str, Path] = {}  # doc -> its PDF in data/inbox (hashing every request is slow)


def _source(doc: str):
    """(manifest, inbox PDF path) of a document, or None."""
    from .ingest import inbox_files, sha256_file
    from .schemas import DocumentManifest

    if not re.fullmatch(r"[0-9a-f]{16}", doc):
        return None
    mpath = WORK / "docs" / doc / "manifest.json"
    if not mpath.exists():
        return None
    m = DocumentManifest.model_validate_json(mpath.read_text())
    src = _SOURCES.get(doc)
    if src is None:
        for path, _ in inbox_files():
            if path.name == m.source_name and sha256_file(path) == m.sha256:
                src = _SOURCES[doc] = path
                break
        else:
            return None
    return m, src


def _original(doc: str, page: int) -> bytes | None:
    """The page as the administrator sent it, WITHOUT blackouts, rendered on the fly so the
    reviewer can read what a blackout covers. Local review only: never written to disk,
    uploaded or published. Restricted pages (payroll, debts, personal) are never shown."""
    import pymupdf

    found = _source(doc)
    if found is None:
        return None
    m, src = found
    if not 1 <= page <= len(m.pages) or m.pages[page - 1].restricted:
        return None
    with pymupdf.open(src) as pdf:
        return pdf[page - 1].get_pixmap(dpi=150).tobytes("png")


def _private_crops(m, t) -> list[dict]:
    """Crop URLs of a private receipt (the transcription's private_receipts entry it came from)."""
    from .receipts import load_transcription

    if not t.privado:
        return []
    for i, pr in enumerate(load_transcription(m).private_receipts):
        if [pr.page] == t.page_nos and pr.concepto == t.descripcion and pr.total == t.total:
            return [{"url": f"/priv/{m.work_dir_name}/{i}/{k}.png", "campo": c.campo} for k, c in enumerate(pr.crops)]
    return []


def _private_crop(doc: str, idx: int, k: int) -> bytes | None:
    """One amount/period box of a restricted payroll page (PrivateReceipt.crops), rendered on
    the fly from the inbox PDF. Only that box is rendered (PrivateCrop caps its size): never
    the whole page, never stored, uploaded or published."""
    import pymupdf

    from .receipts import load_transcription

    found = _source(doc)
    if found is None:
        return None
    m, src = found
    prs = load_transcription(m).private_receipts
    if not 0 <= idx < len(prs) or not 0 <= k < len(prs[idx].crops):
        return None
    pr, c = prs[idx], prs[idx].crops[k]
    if not 1 <= pr.page <= len(m.pages) or not m.pages[pr.page - 1].restricted:
        return None  # private receipts only exist on restricted pages
    with pymupdf.open(src) as pdf:
        pg = pdf[pr.page - 1]
        r = pg.rect  # displayed page (rotation applied); get_pixmap's clip uses the same space
        clip = pymupdf.Rect(r.x0 + c.x0 * r.width, r.y0 + c.y0 * r.height, r.x0 + c.x1 * r.width, r.y0 + c.y1 * r.height)
        return pg.get_pixmap(dpi=200, clip=clip).tobytes("png")


def serve(port: int = 8790) -> None:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200) -> None:
            self._send(
                status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8"
            )

        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return
            if self.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/queue":
                self._json(queue())
            elif m := re.fullmatch(r"/img/([0-9a-f]{16})/(\d{1,4})\.webp", self.path):
                img = _image(m.group(1), int(m.group(2)))
                if img:
                    self._send(200, img.read_bytes(), "image/webp")
                else:
                    self._send(404, b"not found", "text/plain")
            elif m := re.fullmatch(r"/orig/([0-9a-f]{16})/(\d{1,4})\.png", self.path):
                png = _original(m.group(1), int(m.group(2)))
                if png:
                    self._send(200, png, "image/png")
                else:
                    self._send(404, b"not found", "text/plain")
            elif m := re.fullmatch(r"/priv/([0-9a-f]{16})/(\d{1,3})/(\d{1,2})\.png", self.path):
                png = _private_crop(m.group(1), int(m.group(2)), int(m.group(3)))
                if png:
                    self._send(200, png, "image/png")
                else:
                    self._send(404, b"not found", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok():
                return
            if self.path != "/api/action" or self.headers.get("X-Review") != "1":
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
                return
            try:
                length = max(0, min(int(self.headers.get("Content-Length", "0")), 100_000))
                apply(json.loads(self.rfile.read(length)))
            except (ValueError, KeyError, TypeError) as e:
                self._json({"error": str(e)}, 400)
                return
            self._json({"ok": True})

        def log_message(self, *args) -> None:  # quiet
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Revisión: http://127.0.0.1:{port}/  (Ctrl+C para terminar; luego `make publish-local`)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
