"""Step 9: local review (`make review`), PLAN.md §4.9.

A tiny stdlib HTTP server on 127.0.0.1 with one page (review/index.html). It shows:
- links waiting for a decision (sums, ties, near amounts) and automatic ones;
- receipts transcribed from images that nobody confirmed yet, with editable fields;
- expense lines without a receipt;
and lets any receipt, or any debit of a bank statement (bank.py), be linked to any
line by hand (a 'verified' decision).

Decisions go to data/work/review.json (schemas.ReviewState) and edits of receipt
fields to the transcription file (data/work/extract/<sha16>.tickets.json); the next
`make publish` applies them. Nothing here touches the live site.

Only the redacted renders (pNNN.webp, made from public.pdf) are shown. The server
binds to 127.0.0.1, checks the Host header (DNS rebinding) and requires a custom
header on every POST (so other web pages cannot submit decisions).
"""

from __future__ import annotations

import json
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import WORK
from .schemas import ReviewState

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


def _pages(m, page_nos: list[int]) -> list[dict]:
    restricted = {p.page_no for p in m.pages if p.restricted}
    return [{"doc": m.work_dir_name, "page": n} for n in page_nos if n not in restricted]


def queue() -> dict:
    from .ingest import load_manifests
    from .match import collect, collect_movements, match, match_payments

    state = load_review()
    manifests = load_manifests()
    lines, tickets, lookup = collect(manifests)
    links = match(lines, tickets, state)
    decided = state.links
    movements, mlookup = collect_movements(manifests)
    pay_links = match_payments(lines, movements, state)

    def line_json(lid: int) -> dict:
        m, ln = lookup["lines"][lid]
        return {"id": str(lid), "period": m.period, "rubro": ln.rubro, "concepto": ln.concepto, "detalle": ln.detalle,
                "importe": ln.importe, "verified": lid in state.lines_verified, "pages": _pages(m, [ln.page_no or 1])}  # fmt: skip

    def ticket_json(tid: int) -> dict:
        m, t = lookup["tickets"][tid]
        return {"id": str(tid), "kind": t.kind, "letra": t.letra, "fecha": t.fecha, "proveedor": t.proveedor,
                "descripcion": t.descripcion, "total": t.total, "source": t.source, "confidence": t.confidence,
                "verified": t.verified or tid in state.tickets_verified, "pages": _pages(m, t.page_nos)}  # fmt: skip

    def movement_json(mid: int) -> dict:
        # Same shape as a receipt, so the page shows both with the same cards.
        m, mv = mlookup[mid]
        detail = "; ".join(f"{i.descripcion} ×{i.cantidad}: ${i.importe:,.2f}" for i in mv.items) or None
        return {"id": str(mid), "type": "payment", "kind": "gastos bancarios" if mv.kind == "gastos" else "pago bancario",
                "letra": None, "fecha": mv.fecha, "period": mv.period, "proveedor": mv.descripcion, "descripcion": detail,
                "total": mv.importe, "source": "banco", "confidence": 1.0, "verified": True, "pages": _pages(m, mv.page_nos)}  # fmt: skip

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
    evidence_periods = {t.period for t in tickets} | {mv.period for mv in movements}
    return {
        "groups": groups,
        "receipts": [ticket_json(t.id) for t in tickets if lookup["tickets"][t.id][1].source != "qr" or t.id not in linked_tickets],
        "unmatched_lines": [line_json(ln.id) for ln in lines if ln.id not in linked_lines and ln.period in evidence_periods],
        "unused_receipts": [ticket_json(t.id) for t in tickets if t.id not in linked_tickets],
        # Everything, for linking by hand from the page (any receipt to any line).
        "all_receipts": [
            {"id": str(t.id), "period": t.period, "total": t.total, "text": t.text,
             "proveedor": lookup["tickets"][t.id][1].proveedor, "descripcion": lookup["tickets"][t.id][1].descripcion,
             "kind": lookup["tickets"][t.id][1].kind, "fecha": lookup["tickets"][t.id][1].fecha,
             "pages": _pages(lookup["tickets"][t.id][0], lookup["tickets"][t.id][1].page_nos),
             "linked": t.id in linked_tickets}
            for t in sorted(tickets, key=lambda x: (x.period or "", x.text))
        ],  # fmt: skip
        "all_movements": [
            {**movement_json(mv.id), "linked": mv.id in linked_movements}
            for mv in sorted(movements, key=lambda x: (x.period or "", -x.total))
        ],
        "rejected": len(state.rejected_pairs()) + sum(1 for v in state.payments.values() if v == "rejected"),
    }  # fmt: skip


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
    if kind == "link":
        key = f"{int(action['line_id'])}:{int(action['ticket_id'])}"
        decision = action.get("decision")
        if decision in ("verified", "rejected"):
            state.links[key] = decision
        else:
            state.links.pop(key, None)
    elif kind == "payment":
        key = f"{int(action['line_id'])}:{int(action['movement_id'])}"
        decision = action.get("decision")
        if decision in ("verified", "rejected"):
            state.payments[key] = decision
        else:
            state.payments.pop(key, None)
    elif kind in ("ticket", "line"):
        target = state.tickets_verified if kind == "ticket" else state.lines_verified
        eid = int(action["id"])
        if action.get("verified") and eid not in target:
            target.append(eid)
        elif not action.get("verified") and eid in target:
            target.remove(eid)
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

    state = load_review()
    manifests = load_manifests()
    lines, tickets, _ = collect(manifests)
    mids = {mv.id for mv in collect_movements(manifests)[0]}
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
