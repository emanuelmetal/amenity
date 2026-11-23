"""Step 6: link expense lines to receipts (PLAN.md §4.6).

Three passes over each liquidación period, using the receipts attributed to that
period or the one before (bundles arrive with the month's liquidación, and
receipts can be weeks older than the line that pays them):

1. one receipt = one line with the same amount (±0.01), scored up by vendor
   similarity and matching category;
2. several receipts = one line ("mechas, lámparas, etc" = 8 small receipts):
   a bounded subset sum over the receipts still unused;
3. one receipt = several lines (the administrator's receipt for honorarios +
   fotocopias): a bounded subset sum over the lines still unmatched;
4. amounts within 1%, always sent to review.

score >= AUTO links automatically ('auto'), REVIEW <= score < AUTO goes to the
review queue ('pending'), below that the line stays "sin comprobante". Decisions
from review.json win: rejected pairs are never proposed again, verified pairs are
always kept.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace

from rapidfuzz import fuzz

from .schemas import ReviewState

AUTO = 0.9
REVIEW = 0.6
CENT = 0.01
MAX_SUBSET = 10  # receipts per line
MAX_LINES = 4  # lines per receipt
MAX_SEARCH = 200_000  # nodes per subset search (keeps it fast on big months)


@dataclass
class LineRef:
    id: int
    period: str
    importe: float
    text: str  # concepto + detalle + proveedor
    subcategoria: str | None


@dataclass
class TicketRef:
    id: int
    period: str | None
    total: float
    text: str  # proveedor + descripcion
    subcategoria: str | None
    bundle_period: str | None = None  # month of the bundle that brought it (receipts)
    # How many months after the line it may be dated: a cheque (deferred payment) is paid,
    # and debited, months after the expense it pays. 0 for receipts and other debits.
    months_after: int = 0
    # Read from a private payroll page: it may only back a line of its own category (a
    # payslip total must never be offered as the receipt of, say, a plumbing job).
    privado: bool = False


@dataclass
class Link:
    line_id: int
    ticket_id: int
    score: float
    status: str  # auto | pending | verified
    group: list[int] = field(default_factory=list)  # the other tickets/lines matched together
    reason: str = ""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace(".", ""))  # "E.P.E.C." = "EPEC"
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Words too common in conceptos/receipts to say anything about the vendor.
_GENERIC = set(
    "factura recibo ticket presupuesto mano obra trabajo trabajos servicio servicios service compra compras mes "
    "gastos generales varios articulos art. material materiales pago cuota energia electrica edificio complejo alas "
    "torre consorcio sistema viaje para por del de la los las con sin".split()
)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zñ]{4,}", _norm(s)) if w not in _GENERIC}


def vendor_similarity(a: str, b: str) -> float:
    """1.0 when a distinctive word is shared (a vendor's surname, "EPEC"), else fuzzy similarity."""
    if not a.strip() or not b.strip():
        return 0.0
    if _words(a) & _words(b):
        return 1.0
    return fuzz.token_set_ratio(_norm(a), _norm(b)) / 100.0


def _prev(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _months(period: str) -> int:
    y, m = map(int, period.split("-"))
    return y * 12 + m


def _in_window(t: TicketRef, period: str) -> bool:
    """Evidence of the line's month or the one before; a cheque also up to `months_after` later."""
    p = t.bundle_period or t.period
    if not p:
        return False
    return -1 <= _months(p) - _months(period) <= t.months_after


CHEQUE_MONTHS_AFTER = 3


def _gap(ln: LineRef, t: TicketRef) -> int:
    """Months between a line and its evidence (two cheques of the same amount, one a month)."""
    return abs(_months(t.bundle_period or t.period or ln.period) - _months(ln.period))


def _pair_score(line: LineRef, t: TicketRef) -> float:
    diff = abs(line.importe - t.total)
    if diff <= CENT:
        amount = 1.0
    elif line.importe and diff / line.importe <= 0.01:
        amount = 0.6
    else:
        return 0.0
    vendor = vendor_similarity(line.text, t.text)
    category = 1.0 if line.subcategoria and line.subcategoria == t.subcategoria else 0.0
    return 0.6 * amount + 0.25 * vendor + 0.15 * category


def _subset(target: float, values: list[tuple[int, float]], max_k: int) -> list[list[int]]:
    """Up to two subsets of `values` (id, amount) summing to target ±0.01. Two = ambiguous."""
    vals = sorted((v for v in values if 0 < v[1] <= target + CENT), key=lambda v: -v[1])
    suffix = [0.0] * (len(vals) + 1)
    for i in range(len(vals) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + vals[i][1]
    found: list[list[int]] = []
    nodes = 0

    def dfs(i: int, remaining: float, chosen: list[int]) -> None:
        nonlocal nodes
        nodes += 1
        if len(found) >= 2 or nodes > MAX_SEARCH:
            return
        if abs(remaining) <= CENT and len(chosen) >= 2:
            found.append(list(chosen))
            return
        if i >= len(vals) or len(chosen) >= max_k or remaining < -CENT or suffix[i] < remaining - CENT:
            return
        chosen.append(vals[i][0])
        dfs(i + 1, remaining - vals[i][1], chosen)
        chosen.pop()
        dfs(i + 1, remaining, chosen)

    dfs(0, target, [])
    return found


ALL_PASSES = ("exact", "sum", "split", "near", "year")
PAYMENT_PASSES = ("exact", "near")  # bank debits: never combine transfers into sums


def match(
    lines: list[LineRef],
    tickets: list[TicketRef],
    review: ReviewState | None = None,
    passes: tuple[str, ...] = ALL_PASSES,
) -> list[Link]:
    """Also used for bank payments: `tickets` = debits, `review.links` = payment decisions."""
    review = review or ReviewState()
    rejected = review.rejected_pairs()
    rejected |= {(ln.id, t.id) for t in tickets if t.privado for ln in lines if ln.subcategoria != t.subcategoria}
    verified = review.verified_pairs()
    links: list[Link] = []
    used_lines: set[int] = set()
    used_tickets: set[int] = set()

    # Human decisions first. A confirmed receipt larger than its confirmed lines (one
    # receipt for honorarios + fotocopias) keeps the rest available, and so does a line
    # only partly covered by its confirmed receipts.
    line_by_id = {ln.id: ln for ln in lines}
    ticket_by_id = {t.id: t for t in tickets}
    line_left = {ln.id: ln.importe for ln in lines}
    ticket_left = {t.id: t.total for t in tickets}
    for lid, tid in sorted(verified):
        if lid in line_by_id and tid in ticket_by_id:
            links.append(Link(lid, tid, 1.0, "verified", reason="confirmado en la revisión"))
    for lid in {x.line_id for x in links}:
        line_left[lid] -= sum(ticket_by_id[x.ticket_id].total for x in links if x.line_id == lid)
    for tid in {x.ticket_id for x in links}:
        ticket_left[tid] -= sum(line_by_id[x.line_id].importe for x in links if x.ticket_id == tid)
    used_lines |= {lid for lid, left in line_left.items() if left <= CENT}
    used_tickets |= {tid for tid, left in ticket_left.items() if left <= CENT}
    # Kept proposals (another receipt of the same proposal was rejected): proposed again for
    # their line, and not offered to any other line while undecided.
    for lid, tid in sorted(review.held_pairs()):
        if (
            lid in line_by_id
            and tid in ticket_by_id
            and (lid, tid) not in rejected
            and tid not in used_tickets
        ):
            links.append(
                Link(lid, tid, REVIEW, "pending", reason="propuesta que quedó al rechazar otro comprobante")
            )
            used_tickets.add(tid)
    already = {(x.line_id, x.ticket_id) for x in links}

    periods = sorted({ln.period for ln in lines})
    for period in periods:
        # Work on what is still unaccounted for of each line and receipt.
        p_lines = [
            replace(ln, importe=round(line_left[ln.id], 2))
            for ln in lines
            if ln.period == period and ln.id not in used_lines
        ]
        p_tickets = [
            replace(t, total=round(ticket_left[t.id], 2))
            for t in tickets
            # By the bundle's month (an old receipt is billed in the liquidación it came with);
            # its own date's month is for showing it, and would make monthly same-amount
            # vendors ambiguous.
            if _in_window(t, period) and t.id not in used_tickets
        ]
        rejected = rejected | already  # never propose a pair twice

        # 1. one-to-one, exact amounts only (a near amount may really be a sum: passes 2-3).
        pairs = sorted(
            (
                (_pair_score(ln, t), ln, t)
                for ln in p_lines
                for t in p_tickets
                if (ln.id, t.id) not in rejected and abs(ln.importe - t.total) <= CENT
            ),
            key=lambda x: (-x[0], _gap(x[1], x[2])),  # equal score: the closest month first
        )
        for score, ln, t in pairs:
            if score < REVIEW or ln.id in used_lines or t.id in used_tickets:
                continue
            twins = sum(1 for x in p_tickets if x.id not in used_tickets and abs(x.total - t.total) <= CENT)
            twin_lines = sum(
                1 for x in p_lines if x.id not in used_lines and abs(x.importe - ln.importe) <= CENT
            )
            same_vendor = vendor_similarity(ln.text, t.text) >= 0.5
            same_category = bool(ln.subcategoria) and ln.subcategoria == t.subcategoria
            if twins == 1 and twin_lines == 1 and (same_vendor or same_category):
                # The only receipt with this exact amount, for the only such line, and something
                # else agrees (vendor or category): confident enough to link without review.
                score = max(score, AUTO)
            links.append(Link(ln.id, t.id, round(min(score, 1.0), 3), "auto" if score >= AUTO else "pending",
                              reason="mismo importe"))  # fmt: skip
            used_lines.add(ln.id)
            used_tickets.add(t.id)

        # 2. several receipts = one line
        for ln in sorted(p_lines, key=lambda x: -x.importe):
            if ln.id in used_lines or "sum" not in passes:
                continue
            pool = [
                (t.id, t.total)
                for t in p_tickets
                if t.id not in used_tickets and (ln.id, t.id) not in rejected
            ]
            found = _subset(ln.importe, pool, MAX_SUBSET)
            if len(found) != 1:
                continue  # none, or ambiguous: leave it for a human
            group = found[0]
            by_id = {t.id: t for t in p_tickets}
            sim = min(vendor_similarity(ln.text, by_id[g].text) for g in group)
            score = 0.92 if sim >= 0.8 else 0.75
            for g in group:
                links.append(Link(ln.id, g, score, "auto" if score >= AUTO else "pending", group=group,
                                  reason=f"suma de {len(group)} comprobantes"))  # fmt: skip
                used_tickets.add(g)
            used_lines.add(ln.id)

        # 3. one receipt = several lines
        for t in sorted(p_tickets, key=lambda x: -x.total):
            if t.id in used_tickets or "split" not in passes:
                continue
            pool = [
                (ln.id, ln.importe)
                for ln in p_lines
                if ln.id not in used_lines and (ln.id, t.id) not in rejected
            ]
            found = _subset(t.total, pool, MAX_LINES)
            if len(found) != 1:
                continue
            group = found[0]
            by_id = {ln.id: ln for ln in p_lines}
            sim = min(vendor_similarity(by_id[g].text, t.text) for g in group)
            score = 0.85 if sim >= 0.5 else 0.65
            for g in group:
                links.append(
                    Link(
                        g,
                        t.id,
                        score,
                        "pending",
                        group=group,
                        reason=f"un comprobante para {len(group)} líneas",
                    )
                )
                used_lines.add(g)
            used_tickets.add(t.id)
        # 4. near amounts (±1%) last, always for review.
        for score, ln, t in sorted(
            (
                (_pair_score(ln, t), ln, t)
                for ln in p_lines
                for t in p_tickets
                if (ln.id, t.id) not in rejected and ln.id not in used_lines and t.id not in used_tickets
            ),
            key=lambda x: (-x[0], _gap(x[1], x[2])),  # equal score: the closest month first
        ):
            if score < REVIEW or ln.id in used_lines or t.id in used_tickets or "near" not in passes:
                continue
            links.append(
                Link(
                    ln.id, t.id, round(min(score, AUTO - 0.01), 3), "pending", reason="importe parecido (±1%)"
                )
            )
            used_lines.add(ln.id)
            used_tickets.add(t.id)
    if "year" in passes:
        links += _year_pass(lines, tickets, line_left, ticket_left, used_lines, used_tickets, rejected | already)
    return links


def _year_pass(lines, tickets, line_left, ticket_left, used_lines, used_tickets, rejected) -> list[Link]:
    """5. The administrator may hand in a late or lost receipt in any month of the ejercicio
    (the rendición is yearly, CCyC art. 2067 e): a line still without a receipt is offered
    one of the same ejercicio from outside the usual window, with the exact amount and the
    vendor or the category agreeing; the closest month wins, a tie is left for a human.
    Always for review, never automatic."""
    from .config import ejercicio

    def months_away(ln: LineRef, t: TicketRef) -> int:
        return min(abs(_months(p) - _months(ln.period)) for p in (t.period, t.bundle_period) if p)

    out: list[Link] = []
    for ln in sorted(lines, key=lambda x: (x.period, -x.importe)):
        if ln.id in used_lines:
            continue
        left = round(line_left[ln.id], 2)
        cands = [
            t for t in tickets
            if t.id not in used_tickets and (ln.id, t.id) not in rejected and not _in_window(t, ln.period)
            # handed in late, maybe, but not dated after the gasto it pays
            and t.period is not None and t.period <= ln.period and ejercicio(t.period) == ejercicio(ln.period)
            and (t.bundle_period is None or t.period <= t.bundle_period)  # a date after its bundle: misread
            and abs(round(ticket_left[t.id], 2) - left) <= CENT
            and (vendor_similarity(ln.text, t.text) >= 0.5 or (ln.subcategoria and ln.subcategoria == t.subcategoria))
        ]  # fmt: skip
        if not cands:
            continue
        best = min(months_away(ln, t) for t in cands)
        closest = [t for t in cands if months_away(ln, t) == best]
        if len(closest) != 1:
            continue  # two equal candidates as close: a human decides
        t = closest[0]
        score = _pair_score(replace(ln, importe=left), replace(t, total=left))
        out.append(Link(ln.id, t.id, round(min(score, AUTO - 0.01), 3), "pending",
                        reason="mismo importe, otro mes del ejercicio"))  # fmt: skip
        used_lines.add(ln.id)
        used_tickets.add(t.id)
    return out


def collect(manifests) -> tuple[list[LineRef], list[TicketRef], dict]:
    """Lines and receipts of all published documents, plus id -> record lookups."""
    from .classify import classify_text
    from .config import PHASE_KINDS
    from .extract import load_extract
    from .ids import expense_line_ids, ticket_ids
    from .schemas import Comprobantes, Liquidacion

    lines: list[LineRef] = []
    tickets: list[TicketRef] = []
    lookup: dict = {"lines": {}, "tickets": {}}
    for m in manifests:
        if m.kind not in PHASE_KINDS:
            continue
        ext = load_extract(m)
        if isinstance(ext, Liquidacion):
            for lid, ln in zip(expense_line_ids(ext), ext.lines, strict=True):
                text = " ".join(x for x in (ln.concepto, ln.detalle, ln.proveedor) if x)
                # Unclassified lines (extract without the CLI's classify step) get their category
                # here: the private-receipt guard in match() relies on it.
                sub = ln.subcategoria or classify_text(text)[0]
                lines.append(LineRef(lid, ext.period, ln.importe, text, sub))
                lookup["lines"][lid] = (m, ln)
        elif isinstance(ext, Comprobantes):
            for tid, t in zip(ticket_ids(m.work_dir_name, ext.tickets), ext.tickets, strict=True):
                if t.total is None:
                    continue
                text = " ".join(x for x in (t.proveedor, t.descripcion) if x)
                tickets.append(TicketRef(tid, t.period, t.total, text, t.subcategoria, m.period, privado=t.privado))
                lookup["tickets"][tid] = (m, t)
    return lines, tickets, lookup


# Bank boilerplate that says nothing about who was paid.
_BANK_NOISE = re.compile(
    r"TRANSF\.\S*|\b(MISMO|DISTINTO)\b|\bTIT(ULAR)?\b\.?|(PAGO )?DE HABER|DEBITO (DIRECTO|INMEDIATO)|DEBIN-?|"
    r"\[oculto\]|\b\d{6,}\b|[-/]\d+[-/]?",
    re.IGNORECASE,
)


def movement_text(descripcion: str) -> str:
    return re.sub(r"\s+", " ", _BANK_NOISE.sub(" ", descripcion)).strip()


def collect_movements(manifests) -> tuple[list[TicketRef], dict]:
    """Payment evidence of all published receipts documents as match candidates (bank debits
    and cheques not cleared yet, payments.py), plus id -> payments.Payment."""
    from .classify import classify_text
    from .payments import collect_payments

    refs: list[TicketRef] = []
    lookup: dict = {}
    for p in collect_payments(manifests):
        text = movement_text(p.mv.descripcion)
        if p.cheque and p.cheque.beneficiario and p.cheque.beneficiario not in text:
            text = f"{text} {p.cheque.beneficiario}"  # who it paid: helps tell the line
        is_cheque = p.cheque is not None or p.mv.kind == "cheque" or "CHEQUE" in p.mv.descripcion.upper()
        refs.append(TicketRef(p.id, p.mv.period, p.mv.importe, text, classify_text(text)[0],
                              months_after=CHEQUE_MONTHS_AFTER if is_cheque else 0))  # fmt: skip
        lookup[p.id] = p
    return refs, lookup


def match_payments(
    lines: list[LineRef], movements: list[TicketRef], review: ReviewState | None = None
) -> list[Link]:
    """Expense lines <-> bank debits. Decisions come from review.payments."""
    review = review or ReviewState()
    return [
        replace(x, reason=x.reason.replace("importe", "importe del pago"))
        for x in match(lines, movements, ReviewState(links=review.payments), passes=PAYMENT_PASSES)
    ]
