"""Step 10: publish to D1 + R2 (local Miniflare state or remote).

Order matters for privacy:
1. Upload new or changed files to R2: public.pdf (already redacted by ingest)
   and the WebP of every non-restricted page. Uploads are tracked by content
   hash in data/work/uploaded-<target>.json, so a re-ingest that changes
   redactions re-uploads (overwrites) the file.
2. Apply data/out/publish.sql to D1: upserts for documents/pages/periods,
   full replace of each period's lines and each reglamento's articles, FTS
   rebuild. Every published string goes through redact.redact_text.
3. Delete from R2 the renders of pages that are now restricted.

Only document kinds in config.PHASE_KINDS are ever published.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import wrangler
from .config import OUT, PHASE_KINDS, REPO, WORK
from .extract import load_extract
from .ingest import doc_dir, load_manifests
from .redact import redact_text
from .schemas import DocumentManifest, Liquidacion, Reglamento


def q(v: object) -> str:
    """SQL literal. Only used for pipeline-generated values, still escaped properly."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int | float):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def qr(v: str | None) -> str:
    """Redacted SQL string literal: for every free-text field that reaches the site."""
    return q(redact_text(v))


def pdf_key(m: DocumentManifest) -> str:
    return f"docs/{m.work_dir_name}.pdf"


def page_key(m: DocumentManifest, page_no: int) -> str:
    return f"pages/{m.work_dir_name}/p{page_no:03d}.webp"


def public_pdf(m: DocumentManifest) -> Path:
    """The redacted PDF built by ingest (the only PDF ever uploaded)."""
    p = doc_dir(m) / "public.pdf"
    if not p.exists():
        raise FileNotFoundError(f"{m.source_name}: public.pdf missing, run `make ingest` again")
    return p


def publishable(manifests: list[DocumentManifest]) -> list[DocumentManifest]:
    return [m for m in manifests if m.kind in PHASE_KINDS]


def build_sql(manifests: list[DocumentManifest]) -> str:
    stmts: list[str] = []
    for m in publishable(manifests):
        stmts.append(
            "INSERT INTO documents (id, kind, period, title, r2_key_pdf, sha256, pages) VALUES "
            f"({m.id}, {q(m.kind)}, {q(m.period)}, {qr(m.title)}, {q(pdf_key(m))}, {q(m.sha256)}, {len(m.pages)}) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, period=excluded.period, title=excluded.title, "
            "r2_key_pdf=excluded.r2_key_pdf, sha256=excluded.sha256, pages=excluded.pages;"
        )
        for p in m.pages:
            stmts.append(
                "INSERT INTO pages (id, document_id, page_no, r2_key_img, text, ocr_engine, has_qr, restricted) VALUES "
                f"({m.page_id(p.page_no)}, {m.id}, {p.page_no}, {q(page_key(m, p.page_no))}, "
                f"{q('' if p.restricted else redact_text(p.text))}, {q(p.ocr_engine)}, {q(p.has_qr)}, {q(p.restricted)}) "
                "ON CONFLICT(id) DO UPDATE SET text=excluded.text, ocr_engine=excluded.ocr_engine, "
                "has_qr=excluded.has_qr, restricted=excluded.restricted, r2_key_img=excluded.r2_key_img;"
            )

        ext = load_extract(m)
        if isinstance(ext, Liquidacion):
            stmts.append(
                f"INSERT INTO periods (id, total, document_id) VALUES ({q(ext.period)}, {q(ext.total)}, {m.id}) "
                "ON CONFLICT(id) DO UPDATE SET total=excluded.total, document_id=excluded.document_id;"
            )
            # Phase 1: replace the period's lines wholesale. Phase 2 (ticket links +
            # review) must switch to stable ids so verified flags and links survive.
            stmts.append(f"DELETE FROM expense_lines WHERE period_id = {q(ext.period)};")
            for ln in ext.lines:
                page_id = m.page_id(ln.page_no) if ln.page_no else None
                stmts.append(
                    "INSERT INTO expense_lines (period_id, rubro, subcategoria, concepto, detalle, proveedor, cuit, "
                    "importe, page_id, confidence, verified) VALUES "
                    f"({q(ext.period)}, {qr(ln.rubro)}, {qr(ln.subcategoria)}, {qr(ln.concepto)}, {qr(ln.detalle)}, "
                    f"{qr(ln.proveedor)}, {qr(ln.cuit)}, {q(ln.importe)}, {q(page_id)}, {q(ln.confidence)}, "
                    f"{q(ln.verified)});"
                )
        elif isinstance(ext, Reglamento):
            stmts.append(f"DELETE FROM reglamento_articles WHERE document_id = {m.id};")
            for a in ext.articles:
                page_ids = [m.page_id(n) for n in a.page_nos]
                stmts.append(
                    "INSERT INTO reglamento_articles (document_id, numero, orden, titulo, texto, page_ids_json, "
                    "verified) VALUES "
                    f"({m.id}, {qr(a.numero)}, {a.orden}, {qr(a.titulo)}, {qr(a.texto)}, "
                    f"{q(json.dumps(page_ids))}, {q(a.verified)});"
                )
    # Sweep: anything published before that is not in the current set goes away.
    ids = ",".join(str(m.id) for m in publishable(manifests)) or "NULL"
    stmts += [
        f"DELETE FROM expense_lines WHERE period_id IN (SELECT id FROM periods WHERE document_id NOT IN ({ids}));",
        f"DELETE FROM periods WHERE document_id IS NULL OR document_id NOT IN ({ids});",
        f"DELETE FROM reglamento_articles WHERE document_id IS NULL OR document_id NOT IN ({ids});",
        f"DELETE FROM pages WHERE document_id NOT IN ({ids});",
        f"DELETE FROM documents WHERE id NOT IN ({ids});",
    ]
    stmts.append((REPO / "db" / "rebuild_fts.sql").read_text())
    return "\n".join(stmts) + "\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish(local: bool) -> None:
    manifests = publishable(load_manifests())
    if not manifests:
        print("Nothing to publish: run `make ingest` first.")
        return
    target = "local" if local else "remote"
    state_path = WORK / f"uploaded-{target}.json"
    state: dict[str, str] = {}
    if state_path.exists():
        loaded = json.loads(state_path.read_text())
        state = loaded if isinstance(loaded, dict) else {}  # old list format: re-upload everything

    def save() -> None:
        state_path.write_text(json.dumps(state, indent=0, sort_keys=True))

    # 1. uploads (new or changed content)
    expected: set[str] = set()
    for m in manifests:
        files = [(pdf_key(m), public_pdf(m), "application/pdf")]
        for p in m.pages:
            if not p.restricted:
                files.append((page_key(m, p.page_no), doc_dir(m) / f"p{p.page_no:03d}.webp", "image/webp"))
        expected |= {k for k, _, _ in files}
        sent = 0
        for key, path, ctype in files:
            digest = _sha(path)
            if state.get(key) != digest:
                wrangler.r2_put(key, path, ctype, local)
                state[key] = digest
                save()
                sent += 1
        print(f"  {m.source_name}: {sent} files uploaded")

    # 2. database
    OUT.mkdir(parents=True, exist_ok=True)
    sql_path = OUT / "publish.sql"
    sql_path.write_text(build_sql(manifests))
    wrangler.d1_file(sql_path, local)

    # 3. everything uploaded before that is no longer published (restricted pages, dropped documents)
    to_delete = sorted(k for k in state if k not in expected)
    for key in to_delete:
        wrangler.r2_delete(key, local)
        state.pop(key, None)
        save()
    if to_delete:
        print(f"  removed {len(to_delete)} files that are no longer published")
    print(f"Published {len(manifests)} documents to {target} D1/R2.")
