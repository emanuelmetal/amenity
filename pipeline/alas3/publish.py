"""Step 10: publish to D1 + R2 (local Miniflare state or remote).

Order matters for privacy:
1. Upload new or changed files to R2: public.pdf (already redacted by ingest)
   and the WebP of every non-restricted page. Uploads are tracked by content
   hash in data/work/uploaded-<target>.json, so a re-ingest that changes
   redactions re-uploads (overwrites) the file.
2. Apply data/out/publish.sql to D1: upserts for documents/pages/periods and
   expense lines (stable ids, see ids.py), full replace of each reglamento's
   articles, sweep of anything no longer published, FTS rebuild. Every published string goes through redact.redact_text.
3. Delete from R2 the renders of pages that are now restricted.

Only document kinds in config.PHASE_KINDS are ever published.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import wrangler
from .actas import load_book
from .classify import classify_text
from .config import OUT, PHASE_KINDS, REPO, WORK
from .extract import load_extract
from .ids import acta_id, acta_item_ids, article_ids, expense_line_ids, obra_id, ticket_ids
from .ingest import doc_dir, load_manifests
from .match import AUTO, collect, collect_movements, match, match_payments
from .redact import redact_text
from .schemas import (
    ActaBook,
    Comprobantes,
    DocumentManifest,
    Liquidacion,
    ObservationLog,
    Reglamento,
    ReviewState,
)


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


def _observations_sql(log: ObservationLog) -> list[str]:
    """The auditor's observations, replaced in full (observations.json is the source). The
    discarded ones stay in that file only: the site shows them nowhere (owner decision)."""
    stmts = ["DELETE FROM observations;"]
    for o in log.observations:
        if o.estado == "descartada":
            continue
        stmts.append(
            "INSERT INTO observations (id, period_id, tipo, titulo, detalle, importe, estado, fecha, respuesta, "
            "fecha_respuesta, line_ids_json, ticket_ids_json, movement_ids_json) VALUES "
            f"({q(o.id)}, {q(o.period)}, {q(o.tipo)}, {qr(o.titulo)}, {qr(o.detalle)}, {q(o.importe)}, "
            f"{q(o.estado)}, {q(o.fecha)}, {qr(o.respuesta or None)}, {q(o.fecha_respuesta)}, "
            f"{q(json.dumps(o.line_ids))}, {q(json.dumps(o.ticket_ids))}, {q(json.dumps(o.movement_ids))});"
        )
    return stmts


def build_sql(
    manifests: list[DocumentManifest],
    review: ReviewState | None = None,
    observations: ObservationLog | None = None,
    book: ActaBook | None = None,
) -> str:
    """`review`: human decisions from review.json (verified lines/receipts, link decisions).
    `observations`: the auditor's log; None leaves the published observations as they are.
    `book`: the actas transcription (actas.py); None reads data/work/extract/actas.json."""
    book = book if book is not None else load_book()
    review = review or ReviewState()
    verified_lines = set(review.lines_verified)
    stmts: list[str] = []
    published_lines: set[int] = set()
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
            r = ext.resumen
            resumen_json = json.dumps(
                [{"concepto": redact_text(i.concepto), "importe": i.importe, "tipo": i.tipo} for i in r.items]
                if r
                else [],
                ensure_ascii=False,
            )
            stmts.append(
                "INSERT INTO periods (id, total, document_id, saldo_inicial, saldo_final, ingresos, egresos, resumen_json) "
                f"VALUES ({q(ext.period)}, {q(ext.total)}, {m.id}, {q(r and r.saldo_inicial)}, {q(r and r.saldo_final)}, "
                f"{q(r and r.ingresos)}, {q(r and r.egresos)}, {q(resumen_json)}) "
                "ON CONFLICT(id) DO UPDATE SET total=excluded.total, document_id=excluded.document_id, "
                "saldo_inicial=excluded.saldo_inicial, saldo_final=excluded.saldo_final, ingresos=excluded.ingresos, "
                "egresos=excluded.egresos, resumen_json=excluded.resumen_json;"
            )
            # Stable ids (ids.py): upsert, then drop the lines that disappeared, so links
            # and review decisions on unchanged lines survive a re-ingest.
            line_ids = expense_line_ids(ext)
            published_lines |= set(line_ids)
            for lid, ln in zip(line_ids, ext.lines, strict=True):
                page_id = m.page_id(ln.page_no) if ln.page_no else None
                verified = ln.verified or lid in verified_lines
                stmts.append(
                    "INSERT INTO expense_lines (id, period_id, rubro, subcategoria, concepto, detalle, proveedor, cuit, "
                    "importe, page_id, confidence, verified, fondo) VALUES "
                    f"({lid}, {q(ext.period)}, {qr(ln.rubro)}, {qr(ln.subcategoria)}, {qr(ln.concepto)}, {qr(ln.detalle)}, "
                    f"{qr(ln.proveedor)}, {qr(ln.cuit)}, {q(ln.importe)}, {q(page_id)}, {q(ln.confidence)}, "
                    f"{q(verified)}, {q(ln.fondo)}) "
                    "ON CONFLICT(id) DO UPDATE SET period_id=excluded.period_id, rubro=excluded.rubro, "
                    "subcategoria=excluded.subcategoria, concepto=excluded.concepto, detalle=excluded.detalle, "
                    "proveedor=excluded.proveedor, cuit=excluded.cuit, importe=excluded.importe, page_id=excluded.page_id, "
                    "confidence=excluded.confidence, verified=excluded.verified, fondo=excluded.fondo;"
                )
            stmts.append(
                f"DELETE FROM expense_lines WHERE period_id = {q(ext.period)} "
                f"AND id NOT IN ({','.join(map(str, line_ids)) or 'NULL'});"
            )
        elif isinstance(ext, Reglamento):
            # Stable ids (comments point at articles): upsert, then drop the ones that disappeared.
            aids = article_ids(m.work_dir_name, ext.articles)
            for aid, a in zip(aids, ext.articles, strict=True):
                page_ids = [m.page_id(n) for n in a.page_nos]
                stmts.append(
                    "INSERT INTO reglamento_articles (id, document_id, numero, orden, titulo, texto, page_ids_json, "
                    "verified) VALUES "
                    f"({aid}, {m.id}, {qr(a.numero)}, {a.orden}, {qr(a.titulo)}, {qr(a.texto)}, "
                    f"{q(json.dumps(page_ids))}, {q(a.verified)}) "
                    "ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id, numero=excluded.numero, "
                    "orden=excluded.orden, titulo=excluded.titulo, texto=excluded.texto, "
                    "page_ids_json=excluded.page_ids_json, verified=excluded.verified;"
                )
            stmts.append(
                f"DELETE FROM reglamento_articles WHERE document_id = {m.id} "
                f"AND id NOT IN ({','.join(map(str, aids)) or 'NULL'});"
            )
    stmts += _receipts_sql(publishable(manifests), review)
    stmts += _actas_sql(publishable(manifests), review, published_lines, book)

    # Sweep: anything published before that is not in the current set goes away.
    ids = ",".join(str(m.id) for m in publishable(manifests)) or "NULL"
    stmts += [
        f"DELETE FROM expense_lines WHERE period_id IN (SELECT id FROM periods WHERE document_id NOT IN ({ids}));",
        f"DELETE FROM periods WHERE document_id IS NULL OR document_id NOT IN ({ids});",
        f"DELETE FROM reglamento_articles WHERE document_id IS NULL OR document_id NOT IN ({ids});",
        f"DELETE FROM pages WHERE document_id NOT IN ({ids});",
        f"DELETE FROM documents WHERE id NOT IN ({ids});",
    ]
    if observations is not None:
        stmts += _observations_sql(observations)
    stmts.append((REPO / "db" / "rebuild_fts.sql").read_text())
    return "\n".join(stmts) + "\n"


def _actas_sql(
    manifests: list[DocumentManifest], review: ReviewState, lines: set[int], book: ActaBook
) -> list[str]:
    """Actas and their items, replaced in full (stable ids, so comments on an acta survive).
    Only folios whose photo is published are referenced; links to expense lines that are not
    published (any more) are dropped with a warning. Never touches the comment tables."""
    stmts = ["DELETE FROM acta_expense_links;", "DELETE FROM acta_items;", "DELETE FROM actas;"]
    from .actas import folio_key

    pages = {
        folio_key(m, p.page_no): m.page_id(p.page_no)
        for m in manifests
        if m.kind == "acta"
        for p in m.pages
        if not p.restricted
    }
    verified = set(review.actas_verified)
    published_actas: dict[str, int] = {}
    for a in book.actas:
        page_ids = [pages[k] for k in a.folios if k in pages]
        if not page_ids:
            print(f"  ! acta {a.key}: none of its folios is published; skipped")
            continue
        aid = acta_id(a)
        published_actas[a.key] = aid
        stmts.append(
            "INSERT INTO actas (id, numero, fecha, tipo, resumen, asistentes_json, page_ids_json, verified) VALUES "
            f"({aid}, {q(a.numero)}, {q(a.fecha)}, {q(a.tipo)}, {qr(a.resumen)}, "
            f"{q(json.dumps([redact_text(x) for x in a.asistentes], ensure_ascii=False))}, "
            f"{q(json.dumps(page_ids))}, {q(a.verified or a.key in verified)});"
        )
        for orden, (iid, it) in enumerate(zip(acta_item_ids(a), a.items, strict=True), start=1):
            stmts.append(
                "INSERT INTO acta_items (id, acta_id, orden, tipo, texto, importe, period_id, observation_ids_json) VALUES "
                f"({iid}, {aid}, {orden}, {q(it.tipo)}, {qr(it.texto)}, {q(it.importe)}, {q(it.period)}, "
                f"{q(json.dumps(it.observaciones))});"
            )
            for lid in dict.fromkeys(it.gastos):
                if lid not in lines:
                    print(f"  ! acta {a.key}, item {orden}: expense line {lid} is not published; link dropped")
                    continue
                stmts.append(
                    f"INSERT INTO acta_expense_links (acta_item_id, expense_line_id) VALUES ({iid}, {lid});"
                )
    return stmts + _obras_sql(book, lines, published_actas)


def _obras_sql(book: ActaBook, lines: set[int], actas: dict[str, int]) -> list[str]:
    """Approved works (Informe para la asamblea), replaced in full. Links to unpublished
    lines or actas are dropped with a warning, like the acta items'."""
    stmts = ["DELETE FROM obra_expense_links;", "DELETE FROM obras;"]
    for o in book.obras:
        oid = obra_id(o)
        acta_ids = []
        for k in o.actas:
            if k in actas:
                acta_ids.append(actas[k])
            else:
                print(f"  ! obra {o.nombre}: acta {k} is not published; link dropped")
        stmts.append(
            "INSERT INTO obras (id, nombre, aprobado, criterio, detalle, acta_ids_json, observation_ids_json) VALUES "
            f"({oid}, {qr(o.nombre)}, {q(o.total_aprobado)}, {q(o.criterio)}, {qr(o.detalle)}, "
            f"{q(json.dumps(acta_ids))}, {q(json.dumps(o.observaciones))});"
        )
        for lid in dict.fromkeys(o.gastos):
            if lid not in lines:
                print(f"  ! obra {o.nombre}: expense line {lid} is not published; link dropped")
                continue
            stmts.append(f"INSERT INTO obra_expense_links (obra_id, expense_line_id) VALUES ({oid}, {lid});")
    return stmts


def _receipts_sql(manifests: list[DocumentManifest], review: ReviewState) -> list[str]:
    """Receipts (tickets + items), expense<->receipt links and tags."""
    stmts: list[str] = []
    all_ids: list[int] = []
    private: dict[int, tuple] = {}  # payroll totals: published only once linked (below)
    for m in manifests:
        ext = load_extract(m)
        if not isinstance(ext, Comprobantes):
            continue
        restricted = {p.page_no for p in m.pages if p.restricted}
        for tid, t in zip(ticket_ids(m.work_dir_name, ext.tickets), ext.tickets, strict=True):
            page_ids = [m.page_id(n) for n in t.page_nos if n not in restricted]
            if t.privado:
                private[tid] = (m, t)
                continue
            if not page_ids:
                continue  # read from private pages only: never published
            all_ids.append(tid)
            verified = t.verified or tid in review.tickets_verified
            stmts.append(
                "INSERT INTO tickets (id, document_id, page_id, page_ids_json, kind, letra, fecha, proveedor, cuit, "
                "tipo_cmp, pto_vta, nro_cmp, cae, total, medio_pago, descripcion, period_id, subcategoria, source, "
                "confidence, verified) VALUES "
                f"({tid}, {m.id}, {page_ids[0]}, {q(json.dumps(page_ids))}, {q(t.kind)}, {q(t.letra)}, {q(t.fecha)}, "
                f"{qr(t.proveedor)}, {qr(t.cuit)}, {q(t.tipo_cmp)}, {q(t.pto_vta)}, {q(t.nro_cmp)}, {q(t.cae)}, "
                f"{q(t.total)}, {qr(t.medio_pago)}, {qr(t.descripcion)}, {q(t.period)}, {q(t.subcategoria)}, "
                f"{q(t.source)}, {q(t.confidence)}, {q(verified)}) "
                "ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id, page_id=excluded.page_id, "
                "page_ids_json=excluded.page_ids_json, kind=excluded.kind, letra=excluded.letra, fecha=excluded.fecha, "
                "proveedor=excluded.proveedor, cuit=excluded.cuit, tipo_cmp=excluded.tipo_cmp, pto_vta=excluded.pto_vta, "
                "nro_cmp=excluded.nro_cmp, cae=excluded.cae, total=excluded.total, medio_pago=excluded.medio_pago, "
                "descripcion=excluded.descripcion, period_id=excluded.period_id, subcategoria=excluded.subcategoria, "
                "source=excluded.source, confidence=excluded.confidence, verified=excluded.verified;"
            )
            stmts.append(f"DELETE FROM ticket_items WHERE ticket_id = {tid};")
            for it in t.items:
                stmts.append(
                    "INSERT INTO ticket_items (ticket_id, descripcion, cantidad, importe) VALUES "
                    f"({tid}, {qr(it.descripcion)}, {q(it.cantidad)}, {q(it.importe)});"
                )
    # Links are recomputed on every publish; review decisions are inputs to match().
    lines, tickets, lookup = collect(manifests)
    line_amount = {ln.id: ln.importe for ln in lines}
    links = match(lines, [t for t in tickets if t.id in set(all_ids) | set(private)], review)
    # A payroll total (private receipt) is published only when a person confirmed its link or
    # the match is confident, as "<document> (documento privado)": no page, no CUIT, and as
    # amount the sum of the lines it backs (already public), never the figure read from the page.
    for tid, (m, t) in private.items():
        backs = [
            x
            for x in links
            if x.ticket_id == tid and (x.status == "verified" or (x.status == "auto" and x.score >= AUTO))
        ]
        if not backs:
            continue
        all_ids.append(tid)
        total = round(sum(line_amount[x.line_id] for x in backs), 2)
        stmts.append(
            "INSERT INTO tickets (id, document_id, page_id, page_ids_json, kind, proveedor, total, descripcion, period_id, "
            "subcategoria, source, confidence, verified) VALUES "
            f"({tid}, {m.id}, NULL, '[]', {q(t.kind)}, {q(t.proveedor)}, {q(total)}, {q(t.descripcion)}, {q(t.period)}, "
            f"{q(t.subcategoria)}, 'manual', 1.0, {q(t.verified or tid in review.tickets_verified)}) "
            "ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id, page_id=NULL, page_ids_json='[]', "
            "kind=excluded.kind, letra=NULL, fecha=NULL, proveedor=excluded.proveedor, cuit=NULL, tipo_cmp=NULL, "
            "pto_vta=NULL, nro_cmp=NULL, cae=NULL, total=excluded.total, medio_pago=NULL, descripcion=excluded.descripcion, "
            "period_id=excluded.period_id, subcategoria=excluded.subcategoria, source='manual', confidence=1.0, "
            "verified=excluded.verified;"
        )
        stmts.append(f"DELETE FROM ticket_items WHERE ticket_id = {tid};")
    stmts.append(f"DELETE FROM tickets WHERE id NOT IN ({','.join(map(str, all_ids)) or 'NULL'});")
    published = set(all_ids)
    stmts.append("DELETE FROM expense_ticket_links;")
    for ln in links:
        if ln.ticket_id not in published or (ln.ticket_id in private and ln.status == "pending"):
            continue
        # 'pending' links are stored as 'auto' with their score: the site labels low scores.
        status = "verified" if ln.status == "verified" else "auto"
        stmts.append(
            f"INSERT INTO expense_ticket_links VALUES ({ln.line_id}, {ln.ticket_id}, {ln.score}, {q(status)});"
        )

    stmts += _bank_sql(manifests, lines, review)

    # Tags (taxonomy.yaml) on lines and receipts.
    stmts.append("DELETE FROM entity_tags;")
    tagged: list[tuple[str, int, str]] = []
    for lid, (_, line) in lookup["lines"].items():
        _, tags = classify_text(f"{line.concepto} {line.detalle or ''} {line.proveedor or ''}")
        tagged += [("expense", lid, tag) for tag in tags]
    for tid, (_, t) in lookup["tickets"].items():
        if tid in published:
            tagged += [("ticket", tid, tag) for tag in t.tags]
    for name in sorted({tag for _, _, tag in tagged}):
        stmts.append(f"INSERT OR IGNORE INTO tags (name) VALUES ({q(name)});")
    for etype, eid, tag in tagged:
        stmts.append(
            "INSERT OR IGNORE INTO entity_tags (entity_type, entity_id, tag_id) "
            f"SELECT {q(etype)}, {eid}, id FROM tags WHERE name = {q(tag)};"
        )
    return stmts


def _bank_sql(manifests: list[DocumentManifest], lines: list, review: ReviewState) -> list[str]:
    """Payment evidence (bank debits, cheques not cleared yet) and its links to expense lines,
    rebuilt on every publish."""
    from .payments import collect_payments

    stmts = ["DELETE FROM expense_payment_links;", "DELETE FROM bank_movements;"]
    published: set[int] = set()
    for p in collect_payments(manifests):
        mv = p.mv
        visible = [
            (pm, n) for pm, n in p.pages if not any(pg.page_no == n and pg.restricted for pg in pm.pages)
        ]
        own = [pm.page_id(n) for pm, n in visible if pm is p.m]  # its statement page, or the cheque's photo
        if not own:
            continue  # read from private pages only: never published (as with receipts)
        page_ids = [pm.page_id(n) for pm, n in visible]
        published.add(p.id)
        items = [{"descripcion": redact_text(i.descripcion), "importe": i.importe, "cantidad": i.cantidad}
                 for i in mv.items]  # fmt: skip
        c = p.cheque
        stmts.append(
            "INSERT INTO bank_movements (id, document_id, page_id, page_ids_json, period_id, fecha, banco, "
            "comprobante, codigo, descripcion, importe, kind, items_json, cheque_numero, cheque_fecha_pago) VALUES "
            f"({p.id}, {p.m.id}, {q(own[0])}, {q(json.dumps(page_ids))}, "
            f"{q(mv.period)}, {q(mv.fecha)}, {qr(p.banco)}, {q(mv.comprobante)}, {q(mv.codigo)}, "
            f"{qr(mv.descripcion)}, {q(mv.importe)}, {q(mv.kind)}, {q(json.dumps(items, ensure_ascii=False))}, "
            f"{q(c.numero if c else None)}, {q(c.fecha_pago if c else None)});"
        )
    movements, _ = collect_movements(manifests)
    for ln in match_payments(lines, [mv for mv in movements if mv.id in published], review):
        status = "verified" if ln.status == "verified" else "auto"
        stmts.append(
            f"INSERT INTO expense_payment_links VALUES ({ln.line_id}, {ln.ticket_id}, {ln.score}, {q(status)});"
        )
    return stmts


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
    from .match import collect_movements
    from .observations import load_observations
    from .review import sync_cheque_decisions

    sql_path.write_text(
        build_sql(manifests, sync_cheque_decisions(collect_movements(manifests)[1]), load_observations())
    )
    wrangler.d1_file(sql_path, local)

    # 3. everything uploaded before that is no longer published (restricted pages, dropped documents)
    to_delete = sorted(k for k in state if k not in expected)
    for key in to_delete:
        wrangler.r2_delete(key, local)
        state.pop(key, None)
        save()
    if to_delete:
        print(f"  removed {len(to_delete)} files that are no longer published")
    # 4. "Preguntale al portal" reads only this copy of the ask_* views (after the R2 cleanup, so
    # a failed copy never leaves unpublished files behind; on failure the copy is emptied)
    from .ask_sync import sync

    sync(local)
    print(f"Published {len(manifests)} documents to {target} D1/R2.")
