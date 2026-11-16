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
from .schemas import Comprobantes, DocumentManifest, Ticket, TicketTranscription

TRANSCRIPTIONS = WORK / "extract"
_EXACT = ("fecha", "cuit", "tipo_cmp", "pto_vta", "nro_cmp", "total", "cae")


def transcription_path(m: DocumentManifest):
    return TRANSCRIPTIONS / f"{m.work_dir_name}.tickets.json"


def load_transcription(m: DocumentManifest) -> TicketTranscription:
    p = transcription_path(m)
    if not p.exists():
        return TicketTranscription()
    return TicketTranscription.model_validate_json(p.read_text())  # fails loudly on bad input


def qr_tickets(m: DocumentManifest) -> list[Ticket]:
    p = doc_dir(m) / "raw" / "qr.json"
    payloads: dict[str, list[str]] = json.loads(p.read_text()) if p.exists() else {}
    by_key: dict[tuple, Ticket] = {}
    for page_no, values in sorted(payloads.items(), key=lambda kv: int(kv[0])):
        for v in values:
            f = parse_arca(v)
            if not f:
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
    # The transcription may leave the CUIT out (or have it masked): compare the rest.
    return ka[1:] == kb[1:] and (not ka[0] or not kb[0] or ka[0] == kb[0])


def build(m: DocumentManifest) -> Comprobantes:
    return build_with_origin(m)[0]


def build_with_origin(m: DocumentManifest) -> tuple[Comprobantes, list[int | None]]:
    """Also returns, per ticket, the index of its transcription entry (None: QR only)."""
    tickets = qr_tickets(m)
    origin: list[int | None] = [None] * len(tickets)
    tr = load_transcription(m)
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
        t.period = t.period or m.period
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

    # Bank statements are parsed, not transcribed; one that fails its balance check is
    # left for a human (its pages stay "to transcribe") and nothing of it is used.
    statements, failed = bank.statements(m)
    covered = {n for t in tickets for n in t.page_nos} | set(tr.other_pages)
    covered |= {n for s in statements for n in s.page_nos}
    covered -= set(failed)
    todo = [p.page_no for p in m.pages if p.page_no not in covered and not p.restricted]
    return Comprobantes(tickets=tickets, other_pages=tr.other_pages, untranscribed=todo, bank=statements), origin
