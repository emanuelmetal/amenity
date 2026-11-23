"""Command line: `uv run alas3 <command>` (wrapped by the Makefile)."""

from __future__ import annotations

import argparse
import sys

from . import links


def cmd_ingest(args: argparse.Namespace) -> int:
    from .classify import classify_liquidacion
    from .extract import extract_document
    from .ingest import doc_dir, ingest_all
    from .schemas import Comprobantes, Liquidacion

    print("Ingest:")
    manifests = ingest_all(force=args.force)
    print("Extract:")
    for m in manifests:
        try:
            result = extract_document(m)
        except Exception as e:  # keep going; report at the end
            print(f"  ! {m.source_name}: {e}")
            continue
        if isinstance(result, Liquidacion):
            classify_liquidacion(result)
            (doc_dir(m) / "extract.json").write_text(result.model_dump_json(indent=2))
            print(f"  {m.source_name}: {len(result.lines)} lines, total={result.total}")
        elif isinstance(result, Comprobantes):
            todo = f", {len(result.untranscribed)} pages to transcribe" if result.untranscribed else ""
            print(f"  {m.source_name}: {len(result.tickets)} receipts{todo}")
            for t in result.tickets:
                # A QR dated long before the bundle is often an old QR image the vendor keeps printing.
                if t.source == "qr" and t.fecha and m.period and t.fecha[:7] < _months_before(m.period, 6):
                    print(f"    ! p.{t.page_nos[0]}: QR voucher {t.pto_vta}-{t.nro_cmp} is dated {t.fecha}; "
                          "if it is not this receipt, add it to ignore_qr in the transcription")  # fmt: skip
            for st in result.bank:
                print(f"    {st.banco} {st.desde}..{st.hasta}: balance OK, {len(st.movements)} payments "
                      f"(pages {st.page_nos[0]}-{st.page_nos[-1]})")  # fmt: skip
        elif result is not None:
            print(f"  {m.source_name}: {len(result.articles)} articles")  # type: ignore[attr-defined]
    return 0


def _months_before(period: str, n: int) -> str:
    y, m = map(int, period.split("-"))
    m -= n
    while m < 1:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


def cmd_validate(_: argparse.Namespace) -> int:
    from .extract import load_extract
    from .ingest import load_manifests
    from .schemas import Liquidacion
    from .validate import check_fondo, check_liquidacion, check_resumen

    problems: list[str] = []
    checked = 0
    for m in load_manifests():
        ext = load_extract(m)
        if isinstance(ext, Liquidacion):
            checked += 1
            problems += check_liquidacion(ext) + check_resumen(ext) + check_fondo(ext)
    from .review import dangling_decisions

    dangling = dangling_decisions()
    problems += [f"review.json: {d} refers to something that no longer exists" for d in dangling]
    from .golden import THRESHOLD
    from .golden import run as golden_run

    score = golden_run()
    if score is not None:
        print(f"golden set: {score.correct}/{score.checked} fields right ({score.accuracy:.1%})")
        for miss in score.misses:
            print(f"  miss {miss}")
        if score.accuracy < THRESHOLD:
            problems.append(f"golden set accuracy {score.accuracy:.1%} < {THRESHOLD:.0%}")
    for p in problems:
        print(f"FAIL {p}")
    print(f"{checked} liquidaciones checked, {len(problems)} problems")
    return 1 if problems else 0


def cmd_review(args: argparse.Namespace) -> int:
    from .review import serve

    serve(args.port)
    return 0


def cmd_match(_: argparse.Namespace) -> int:
    """Receipt coverage per period (what `make review` will show)."""
    from collections import defaultdict

    from .ingest import load_manifests
    from .match import AUTO, collect, match
    from .review import load_review

    lines, tickets, _ = collect(load_manifests())
    links = match(lines, tickets, load_review())
    periods_with_receipts = {t.period for t in tickets}
    by_line = defaultdict(list)
    for ln in links:
        by_line[ln.line_id].append(ln)
    for period in sorted(periods_with_receipts):
        pl = [ln for ln in lines if ln.period == period]
        total = sum(ln.importe for ln in pl)
        if not pl or not total:
            print(f"{period}: receipts but no liquidación lines")
            continue
        covered = sum(ln.importe for ln in pl if ln.id in by_line)
        pending = sum(1 for ln in pl if ln.id in by_line and min(x.score for x in by_line[ln.id]) < AUTO
                      and not all(x.status == "verified" for x in by_line[ln.id]))  # fmt: skip
        print(f"{period}: {len(pl)} lines, {sum(1 for ln in pl if ln.id in by_line)} with receipt "
              f"({covered / total:.0%} of the amount), {pending} to review")  # fmt: skip
    unused = [t for t in tickets if t.id not in {x.ticket_id for x in links}]
    print(f"{len(tickets)} receipts, {len(unused)} not linked to any line")

    from .match import collect_movements, match_payments

    movements, mlookup = collect_movements(load_manifests())
    if movements:
        from .review import sync_cheque_decisions

        pay = match_payments(lines, movements, sync_cheque_decisions(mlookup))
        auto = sum(1 for x in pay if x.status in ("auto", "verified"))
        print(f"{len(movements)} bank payments, {auto} linked, {len(pay) - auto} to review")
        no_backing = [ln for ln in lines if ln.period in periods_with_receipts | {m.period for m in movements}
                      and ln.id not in by_line and ln.id not in {x.line_id for x in pay}]  # fmt: skip
        for ln in no_backing:
            print(f"  without receipt or payment: {ln.period} {ln.text[:60]} {ln.importe:,.2f}")
    return 0


def cmd_review_notes(args: argparse.Namespace) -> int:
    """Rejected links with the reviewer's reason and enough context to fix the data."""
    from .review import queue

    rows = queue()["rejections"]
    noted = [r for r in rows if r["note"]]
    for r in noted:
        n, ln, it = r["note"], r["line"], r["item"]
        pages = ", ".join(f"{p['doc']} p.{p['page']}" for p in it["pages"]) or "sin página pública"
        print(f"[{n['fecha']}] {n['motivo']}" + (f": {n['detalle']}" if n["detalle"] else ""))
        print(f"  gasto     {ln['id']}  {ln['period']}  {ln['concepto']}" + (f" — {ln['detalle']}" if ln["detalle"] else "")
              + f"  ${ln['importe']:,.2f}")  # fmt: skip
        what = "pago" if r["kind"] == "payment" else "comprobante"
        print(f"  {what:<9} {it['id']}  {it.get('fecha') or it.get('period') or ''}  {it.get('proveedor') or ''}  "
              f"${(it.get('total') or 0):,.2f}  ({it.get('kind') or ''}; {pages})")  # fmt: skip
        if it.get("descripcion"):
            print(f"            {it['descripcion'][:160]}")
    print(f"{len(noted)} rejections with a reason, {len(rows) - len(noted)} without")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish import publish

    publish(local=args.local)
    return 0


def cmd_observations(args: argparse.Namespace) -> int:
    """The auditor's observations log; --draft prints the selected ones for the administrator."""
    from .observations import draft, load_observations, report

    log = load_observations()
    if args.draft:
        print(draft(log, tuple(args.estado or ["abierta"]), args.period), end="")
    else:
        print(report(log))
    return 0


def cmd_ejercicio(args: argparse.Namespace) -> int:
    """Year-close check: the administrator's balance and the evidence of the whole ejercicio."""
    from .yearclose import report

    print(report(args.desde), end="")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    if args.action == "new":
        print(links.create(args.kind, args.unit, args.days, args.local))
    elif args.action == "rotate":
        print(links.rotate(args.local))
    elif args.action == "revoke":
        links.revoke(args.local, args.id, args.unit)
        print("ok")
    elif args.action == "list":
        links.list_codes(args.local)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="alas3")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="split, OCR, redact, extract, classify")
    s.add_argument("--force", action="store_true", help="re-process documents already ingested")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("validate", help="sum checks on extracted liquidaciones")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("review", help="local review page for receipts and links")
    s.add_argument("--port", type=int, default=8790)
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("review-notes", help="rejected links with the reviewer's reasons")
    s.set_defaults(fn=cmd_review_notes)

    s = sub.add_parser("match", help="receipt coverage report")
    s.set_defaults(fn=cmd_match)

    s = sub.add_parser("observations", help="auditor's observations log (data/work/observations.json)")
    s.add_argument("--draft", action="store_true", help="print them as a message for the administrator")
    s.add_argument("--period", help="only this month (YYYY-MM)")
    s.add_argument("--estado", action="append", help="states to include in --draft (default: abierta)")
    s.set_defaults(fn=cmd_observations)

    s = sub.add_parser("ejercicio", help="year-close check: balance + evidence of one ejercicio (Sep–Aug)")
    s.add_argument("--desde", help="first month of the ejercicio, e.g. 2025-09 (default: latest balance)")
    s.set_defaults(fn=cmd_ejercicio)

    s = sub.add_parser("publish", help="upload to D1 + R2")
    s.add_argument("--local", action="store_true", help="target local wrangler state instead of Cloudflare")
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("link", help="manage access links")
    s.add_argument("action", choices=["new", "rotate", "revoke", "list"])
    s.add_argument("--kind", choices=["shared", "unit", "admin"], default="shared")
    s.add_argument("--unit")
    s.add_argument("--id", type=int)
    s.add_argument("--days", type=int)
    s.add_argument("--local", action="store_true")
    s.set_defaults(fn=cmd_link)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
