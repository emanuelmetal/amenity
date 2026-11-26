"""Step 4 for receipts: QR data + transcription -> one Ticket per voucher.

Sources, in order of trust:
1. ARCA/AFIP invoice QR codes found by ingest (raw/qr.json): exact date, CUIT,
   type, point of sale, number and total.
2. The transcription in data/work/extract/<sha16>.tickets.json (TicketTranscription):
   vendor, description, items for every receipt, and the only source for photos
   of paper receipts. Written by Claude Code from the page images (PLAN.md §4,
   option A) and confirmed in `make review`.

A transcribed ticket with the same voucher key as a QR ticket is merged into it:
the QR's fields win, the transcription fills the rest. Copies (ORIGINAL /
DUPLICADO / TRIPLICADO) collapse into one ticket listing all their pages.
"""

from __future__ import annotations

import json

from . import bank
from .classify import classify_text
from .config import WORK
from .ingest import doc_dir
from .qr import TIPO_CMP, parse_arca
from .schemas import PRIVATE_CONCEPTS, Comprobantes, DocumentManifest, Ticket, TicketTranscription

TRANSCRIPTIONS = WORK / "extract"
# Restriction reasons a checked transcription lifts (ingest: `checked` map); the rest
# (payroll, personal, manual, debtors) stay private and are never "to transcribe".
CHECKABLE_REASONS = ("no_text", "qr_not_located", "unlocated_identifier", "unchecked_scan")
_EXACT = ("fecha", "cuit", "tipo_cmp", "pto_vta", "nro_cmp", "total", "cae")


def transcription_path(m: DocumentManifest):
    return TRANSCRIPTIONS / f"{m.work_dir_name}.tickets.json"


def load_transcription(m: DocumentManifest) -> TicketTranscription:
    p = transcription_path(m)
    if not p.exists():
        return TicketTranscription()
    return TicketTranscription.model_validate_json(p.read_text())  # fails loudly on bad input


def qr_tickets(m: DocumentManifest, ignore: set[tuple[int, int, int]] | None = None) -> list[Ticket]:
    """ignore: (page, pto_vta, nro_cmp) of QRs that encode another voucher (see IgnoredQR)."""
    ignore = ignore or set()
    p = doc_dir(m) / "raw" / "qr.json"
    payloads: dict[str, list[str]] = json.loads(p.read_text()) if p.exists() else {}
    by_key: dict[tuple, Ticket] = {}
    for page_no, values in sorted(payloads.items(), key=lambda kv: int(kv[0])):
        for v in values:
            f = parse_arca(v)
            if not f or (int(page_no), f["pto_vta"], f["nro_cmp"]) in ignore:
                continue
            kind, letra = TIPO_CMP.get(f["tipo_cmp"], ("otro", None))
            t = Ticket(page_nos=[int(page_no)], kind=kind, letra=letra, source="qr", confidence=1.0, **f)  # type: ignore[arg-type]
            k = t.key()
            if k in by_key:
                if int(page_no) not in by_key[k].page_nos:
                    by_key[k].page_nos.append(int(page_no))
            else:
                by_key[k] = t
    return list(by_key.values())


def _same_voucher(a: Ticket, b: Ticket) -> bool:
    ka, kb = a.key(), b.key()
    if not ka or not kb:
        return False
    # The transcription may leave the CUIT (or have it masked) or the voucher type out:
    # point of sale + number must agree, the others only when both sides have them.
    return ka[2:] == kb[2:] and all(not x or not y or x == y for x, y in ((ka[0], kb[0]), (ka[1], kb[1])))


def build(m: DocumentManifest) -> Comprobantes:
    return build_with_origin(m)[0]


def _next(period: str) -> str:
    y, mth = map(int, period.split("-"))
    return f"{y + 1}-01" if mth == 12 else f"{y}-{mth + 1:02d}"


def build_with_origin(m: DocumentManifest) -> tuple[Comprobantes, list[int | None]]:
    """Also returns, per ticket, the index of its transcription entry (None: QR only)."""
    tr = load_transcription(m)
    tickets = qr_tickets(m, {(q.page, q.pto_vta, q.nro_cmp) for q in tr.ignore_qr})
    origin: list[int | None] = [None] * len(tickets)
    for idx, t in enumerate(tr.tickets):
        target = next((q for q in tickets if _same_voucher(q, t)), None)
        if target is None:
            tickets.append(t.model_copy(deep=True))
            origin.append(idx)
            continue
        exact = {k: getattr(target, k) for k in _EXACT if getattr(target, k) is not None}
        merged = t.model_copy(update=exact, deep=True)
        merged.page_nos = sorted(set(target.page_nos) | set(t.page_nos))
        merged.source, merged.confidence = "qr", 1.0
        if target.kind != "otro":
            merged.kind, merged.letra = target.kind, target.letra
        pos = tickets.index(target)
        tickets[pos] = merged
        origin[pos] = idx

    restricted = {p.page_no for p in m.pages if p.restricted}
    for t in tickets:
        # A receipt belongs to the month of its own date, not to the bundle that brought it
        # (an old invoice billed in a later liquidación). A date after the bundle's next month
        # is a misread: the bundle's month then.
        dated = t.fecha[:7] if t.fecha else None
        t.period = t.period or (dated if dated and m.period and dated <= _next(m.period) else m.period)
        if t.tipo_cmp in TIPO_CMP and (t.kind == "otro" or t.letra is None):
            kind, letra = TIPO_CMP[t.tipo_cmp]
            t.kind = kind if t.kind == "otro" else t.kind
            t.letra = t.letra or letra
        # The transcriber's keywords say what the receipt is for; free text (a work report
        # mentioning "se limpió") only decides when they don't.
        t.subcategoria, t.tags = classify_text(" ".join(t.keywords))
        if t.subcategoria is None:
            t.subcategoria, t.tags = classify_text(
                " ".join([t.proveedor or "", t.descripcion or "", *(i.descripcion for i in t.items)])
            )
    # Never publish data read (even partly) from a private page, e.g. a payroll slip:
    # dropping only its page id would still publish what was transcribed from it.
    keep = [i for i, t in enumerate(tickets) if not set(t.page_nos) & restricted]
    tickets = [tickets[i] for i in keep]
    origin = [origin[i] for i in keep]

    # Totals read from payroll pages: receipts that only say what they are and how much.
    for pr in tr.private_receipts:
        if pr.page not in restricted:
            raise ValueError(f"{m.source_name} p.{pr.page}: private_receipts only for restricted pages")
        doc = PRIVATE_CONCEPTS[pr.concepto]
        keywords = ["sueldo encargado"] if doc == "Recibo de sueldo" else ["cargas sociales"]
        sub, tags = classify_text(" ".join(keywords))
        tickets.append(Ticket(
            page_nos=[pr.page], kind="recibo", proveedor=f"{doc} (documento privado)", descripcion=pr.concepto,
            total=pr.total, keywords=keywords, source="manual", confidence=1.0, privado=True,
            period=pr.periodo or m.period, subcategoria=sub, tags=tags,
        ))  # fmt: skip
        origin.append(None)

    # Bank statements are parsed, not transcribed; one that fails its balance check is
    # left for a human (its pages stay "to transcribe") and nothing of it is used.
    statements, failed = bank.statements(m, {f.page: f.saldo_final for f in tr.bank_closing}, tr.bank_private)
    # A cheque on a private page is never used (as with receipts), nor one whose page nobody
    # checked: its account data and signature must be blacked out (`checked`) before it is shown.
    cheques = [c for c in tr.cheques if c.page not in restricted and c.page in tr.checked]
    covered = {n for t in tickets for n in t.page_nos} | set(tr.other_pages) | {c.page for c in cheques}
    covered |= {n for s in statements for n in s.page_nos}
    covered -= set(failed)
    # A scan that is restricted only until someone checks it (unreadable, QR or identifier not
    # located) still has to be transcribed: skipping it would hide its receipts for good. A
    # checked page is not "done" either: it needs its receipts, or an `other_pages` entry.
    todo = [
        p.page_no
        for p in m.pages
        if p.page_no not in covered
        and (not p.restricted or p.restricted_reason in CHECKABLE_REASONS)
    ]
    return Comprobantes(
        tickets=tickets, other_pages=tr.other_pages, untranscribed=todo, bank=statements, cheques=cheques
    ), origin
