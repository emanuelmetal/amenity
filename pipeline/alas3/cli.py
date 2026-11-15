"""Command line: `uv run alas3 <command>` (wrapped by the Makefile)."""

from __future__ import annotations

import argparse
import sys

from . import links


def cmd_ingest(args: argparse.Namespace) -> int:
    from .classify import classify_liquidacion
    from .extract import extract_document
    from .ingest import doc_dir, ingest_all
    from .schemas import Liquidacion

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
        elif result is not None:
            print(f"  {m.source_name}: {len(result.articles)} articles")  # type: ignore[attr-defined]
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    from .extract import load_extract
    from .ingest import load_manifests
    from .schemas import Liquidacion
    from .validate import check_liquidacion

    problems: list[str] = []
    checked = 0
    for m in load_manifests():
        ext = load_extract(m)
        if isinstance(ext, Liquidacion):
            checked += 1
            problems += check_liquidacion(ext)
    for p in problems:
        print(f"FAIL {p}")
    print(f"{checked} liquidaciones checked, {len(problems)} problems")
    return 1 if problems else 0


def cmd_publish(args: argparse.Namespace) -> int:
    from .publish import publish

    publish(local=args.local)
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
