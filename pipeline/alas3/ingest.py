"""Step 1–3: inventory, text layer (+OCR), privacy policy, redacted PDF, renders.

Output per document in data/work/docs/<sha16>/:
  manifest.json    DocumentManifest (redacted text: safe to publish)
  raw/pNNN.txt     unredacted text, used only by extraction; never published
  ocr.pdf          OCRmyPDF output when the document had scanned pages
  public.pdf       the ONLY PDF that is ever published: restricted pages blanked,
                   debt blocks and personal identifiers blacked out (text and pixels),
                   metadata removed
  pNNN.webp        page renders, made from public.pdf (so they carry the same redactions)
  raw/qr.json      receipts only: decoded QR payloads per page (unredacted, never published);
                   every QR and 1D barcode found is blacked out in public.pdf (invoice
                   QRs and old AFIP barcodes encode the issuer's CUIT, a person's CUIL
                   for monotributo vendors)

Manual overrides (human review): data/work/restrict.json
  {"<sha16>": {"restrict": [3, 4], "allow": [7]}}
`restrict` forces pages private; `allow` publishes a page the automatic policy
restricted (e.g. a scanned page with no OCR text, after looking at it); `full` publishes
a page exactly as the administrator sent it: no blackout and no masking at all (names,
CUIL, addresses stay visible and searchable). Only on the owner's explicit decision, page
by page (e.g. an insurance policy the consortium pays for); `restrict` still wins.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pymupdf
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from . import bank, ocr, qr, redact
from .config import INBOX, KIND_MAP, MIN_TEXT_CHARS, PHASE_KINDS, RENDER_DPI, WEBP_QUALITY, WORK
from .schemas import DocumentManifest, PageRecord

REGISTRY = WORK / "registry.json"
OVERRIDES = WORK / "restrict.json"
RESTRICTED_NOTE = "Página no publicada por privacidad (datos personales)."
# A text page whose images cover at least this share of the page is also OCR'd from pixels
# (e.g. a pasted scan of a payroll slip inside a born-digital PDF).
MIXED_IMAGE_COVERAGE = 0.3

# Files dropped directly in data/inbox/ are classified by name (first match wins).
NAME_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"reglamento", re.I), "reglamento"),
    (re.compile(r"resumen\s*_?gastos|liquidaci[oó]n|expensas", re.I), "liquidacion"),
    (re.compile(r"comprobante|factura|ticket", re.I), "comprobantes"),
    (re.compile(r"\bacta", re.I), "acta"),
]

_PERIOD_PATTERNS = [
    (re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])(?!\d)"), "ym"),  # 2026-10, 2026_10
    (re.compile(r"(?<!\d)(0[1-9]|1[0-2])(20\d{2})(?!\d)"), "my"),  # _012026
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)"), "ym"),  # _202601
]
_PERIOD_IN_TEXT = re.compile(r"(?i)per[ií]odo:?\s+(0[1-9]|1[0-2])/(20\d{2})")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_dir(manifest: DocumentManifest) -> Path:
    return WORK / "docs" / manifest.work_dir_name


def _doc_id(sha: str) -> int:
    """Stable small integer id per document hash."""
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    if sha not in reg:
        reg[sha] = max(reg.values(), default=0) + 1
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(reg, indent=2))
    return reg[sha]


def layout_rows(page: pymupdf.Page) -> list[tuple[str, pymupdf.Rect]]:
    """One visual row per entry (table cells joined by two spaces), with its bounding box.

    Plain get_text() emits each table cell on its own line, which makes
    liquidación rows impossible to parse; grouping words by baseline fixes that.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    rows: list[tuple[float, list[tuple[float, float, float, float, str]]]] = []
    for x0, y0, x1, y1, w, *_ in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (y0 + y1) / 2
        if rows and abs(rows[-1][0] - yc) <= max(2.5, (y1 - y0) * 0.35):
            rows[-1][1].append((x0, y0, x1, y1, w))
        else:
            rows.append((yc, [(x0, y0, x1, y1, w)]))
    out = []
    for _, cells in rows:
        cells.sort()
        text, prev_x1 = "", None
        rect = pymupdf.Rect(cells[0][:4])
        for x0, y0, x1, y1, w in cells:
            if prev_x1 is not None:
                text += "  " if x0 - prev_x1 > 8 else " "
            text += w
            prev_x1 = x1
            rect |= pymupdf.Rect(x0, y0, x1, y1)
        out.append((text, rect))
    return out


def layout_text(page: pymupdf.Page) -> str:
    return "\n".join(t for t, _ in layout_rows(page))


def guess_period(name: str, text: str = "") -> str | None:
    for pattern, order in _PERIOD_PATTERNS:
        m = pattern.search(name)
        if m:
            y, mo = (m.group(1), m.group(2)) if order == "ym" else (m.group(2), m.group(1))
            return f"{y}-{mo}"
    m = _PERIOD_IN_TEXT.search(text)
    return f"{m.group(2)}-{m.group(1)}" if m else None


def classify_name(name: str) -> str:
    for pattern, kind in NAME_RULES:
        if pattern.search(name):
            return kind
    return "otro"


def _title(kind: str, period: str | None, path: Path) -> str:
    # Admin system prefixes like "039_20260211151324_" are noise.
    stem = re.sub(r"^\d+_\d{8,14}_", "", path.stem).replace("_", " ").strip()
    base = {
        "liquidacion": "Liquidación de expensas",
        "comprobantes": "Comprobantes",
        "reglamento": stem or "Reglamento",
        "acta": "Acta de comisión",
        "otro": stem,
    }[kind]
    return f"{base} {period}" if period and kind in ("liquidacion", "comprobantes") else base


class _Override(BaseModel):
    model_config = ConfigDict(extra="forbid")
    restrict: list[int] = []
    allow: list[int] = []
    full: list[int] = []  # published unredacted: the owner's explicit decision, page by page


def load_overrides(known_sha16: set[str] | None = None) -> dict[str, _Override]:
    """Reviewer overrides. Fails loudly on anything malformed: a silently ignored
    override would publish a page someone decided to hide."""
    if not OVERRIDES.exists():
        return {}
    try:
        data = TypeAdapter(dict[str, _Override]).validate_json(OVERRIDES.read_text())
    except ValidationError as e:
        raise SystemExit(f"{OVERRIDES}: invalid overrides:\n{e}") from e
    bad = [k for k in data if not re.fullmatch(r"[0-9a-f]{16}", k)]
    if known_sha16 is not None:
        bad += [k for k in data if k not in known_sha16 and k not in bad]
    if bad:
        raise SystemExit(
            f"{OVERRIDES}: unknown document keys {bad} (use the 16-char sha prefix of a file in data/inbox)"
        )
    return data


def _image_coverage(page: pymupdf.Page) -> float:
    area = abs(page.rect)
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return min(1.0, covered / area) if area else 0.0


def build_public_pdf(src: Path, dest: Path, plans: list[tuple[PageRecord, list[pymupdf.Rect]]]) -> None:
    """Writes the publishable PDF: restricted pages replaced, sensitive areas removed (text + pixels)."""
    with pymupdf.open(src) as doc:
        for rec, rects in plans:
            i = rec.page_no - 1
            if rec.restricted:
                rect = doc[i].rect
                doc.delete_page(i)
                blank = doc.new_page(pno=i, width=rect.width, height=rect.height)
                blank.insert_text((72, 96), RESTRICTED_NOTE, fontsize=12)
                continue
            if rects:
                page = doc[i]
                for r in rects:
                    page.add_redact_annot(r + (-1, -1, 1, 1), fill=(0, 0, 0))
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.save(dest, garbage=4, deflate=True)


def ingest_file(path: Path, kind: str, force: bool = False) -> DocumentManifest:
    sha = sha256_file(path)
    manifest = DocumentManifest(
        id=_doc_id(sha),
        kind=kind,  # type: ignore[arg-type]
        title="",
        source_name=path.name,
        sha256=sha,
    )
    out = doc_dir(manifest)
    mpath = out / "manifest.json"
    if mpath.exists() and not force:
        return DocumentManifest.model_validate_json(mpath.read_text())

    (out / "raw").mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("p*.webp"), *(out / "raw").glob("p*.bank.txt")]:
        old.unlink()  # a page that became restricted must not keep a stale render or statement text

    with pymupdf.open(path) as doc:
        # A scan = little text AND an image covering a good part of the page. A short
        # born-digital page (no images) has nothing to hide beyond its text.
        scanned = {
            i
            for i, page in enumerate(doc)
            if len(page.get_text().strip()) < MIN_TEXT_CHARS and _image_coverage(page) >= MIXED_IMAGE_COVERAGE
        }
    src = path
    if scanned:
        src = ocr.ocr_document(path, out / "ocr.pdf") or path  # no OCR → those pages fail closed (no_text)

    ov = load_overrides().get(manifest.work_dir_name, _Override())
    checked: dict = {}
    if kind == "comprobantes":
        from .receipts import load_transcription

        checked = load_transcription(manifest).checked  # fails loudly on a bad file
    plans: list[tuple[PageRecord, list[pymupdf.Rect]]] = []
    carry = False  # a debt block that continues from the previous page
    qr_payloads: dict[int, list[str]] = {}
    with pymupdf.open(src) as doc:
        for i, page in enumerate(doc):
            page_no = i + 1
            rows = layout_rows(page)
            row_texts = [t for t, _ in rows]
            policy_rows = list(row_texts)
            mixed = i not in scanned and _image_coverage(page) >= MIXED_IMAGE_COVERAGE
            unchecked_image = False
            if mixed:
                # What the embedded image shows must pass the same checks as the text.
                pixel_text = ocr.ocr_page_pixels(page)
                if not pixel_text.strip():
                    unchecked_image = True  # Tesseract unavailable or unreadable image: fail closed
                policy_rows += pixel_text.split("\n")

            policy = redact.page_policy(policy_rows, scanned=i in scanned, carry_in=carry)
            # Only a liquidación's debt list runs across pages; a receipts bundle is many
            # unrelated documents, so a block never continues onto the next page there.
            carry = policy.open_block and kind == "liquidacion"
            reason = policy.restricted
            if reason is None and unchecked_image:
                reason = "no_text"
            if reason is None and any(j >= len(rows) for j in policy.hidden_lines):
                reason = "debtors"  # the debt list is inside an image: it cannot be blacked out by row

            hidden = set(policy.hidden_lines)
            if kind == "comprobantes" and bank.is_statement_page("\n".join(row_texts)):
                # Owners' payments (who paid tells who did not) and salary/refund transfers
                # (they name a person): blacked out. The full text is
                # kept privately so bank.py can still check the balance.
                hidden |= bank.private_lines(row_texts)
                bank.private_text_path(manifest, page_no).write_text("\n".join(row_texts))
            # Areas a person marked on a checked scan: blacked out in the image below, and the
            # OCR text read from them is dropped too (it would still be searchable).
            manual: list[pymupdf.Rect] = []
            if kind == "comprobantes":
                for b in checked.get(page_no, []):
                    w, h = page.rect.width, page.rect.height
                    shown = pymupdf.Rect(b.x0 * w, b.y0 * h, b.x1 * w, b.y1 * h)
                    manual.append((shown * page.derotation_matrix) & page.mediabox)
                    # Text positions may be reported in either orientation: hide rows touching either.
                    hidden |= {
                        j
                        for j, (_, rr) in enumerate(rows)
                        if rr.intersects(shown) or rr.intersects(manual[-1])
                    }

            rects: list[pymupdf.Rect] = list(manual)
            visible: list[str] = []
            for j, (text, rect) in enumerate(rows):
                if j in hidden:
                    # Full page width: OCR word boxes are approximate and amounts may sit far right.
                    rects.append(pymupdf.Rect(page.rect.x0, rect.y0 - 2, page.rect.x1, rect.y1 + 2))
                else:
                    visible.append(text)
            # Extraction only ever sees what is published (hidden debt rows never become expense lines).
            (out / "raw" / f"p{page_no:03d}.txt").write_text("\n".join(visible))

            strings = redact.sensitive_strings("\n".join(visible + policy_rows[len(rows) :]))
            for s_ in strings:
                hits = page.search_for(s_)
                if not hits and reason is None:
                    reason = "unlocated_identifier"  # masked in text but cannot be blacked out in the image
                rects += hits

            has_qr = False
            if kind == "comprobantes":
                rejected: list[pymupdf.Rect] = []
                found = qr.find_qr(page, rejected)
                invoice = bool(qr.ARCA_MARKERS.search("\n".join(policy_rows)))
                if invoice and not any(f.payload for f in found):
                    # Small or blurry QRs on scans only show up at a higher resolution.
                    for f in qr.find_qr(page, rejected, dpis=qr.RETRY_DPIS):
                        same = next((g for g in found if qr.overlap(f.rect, g.rect)), None)
                        if same is None:
                            found.append(f)
                        else:
                            same.payload = same.payload or f.payload
                barcodes = qr.find_barcodes(page)
                has_qr = bool(found)
                rects += [f.rect for f in found] + barcodes
                qr_payloads[page_no] = [f.payload for f in found if f.payload]
                decoded = any(f.payload for f in found)
                # Older invoices carry the CAE as a 1D barcode instead of a QR: located = blacked out.
                if invoice and not decoded and ((not found and not barcodes) or rejected) and reason is None:
                    # An electronic invoice whose QR (it encodes the issuer's CUIT, a person's
                    # CUIL for monotributistas) was not found, or may be a detection we
                    # discarded as noise: fail closed. A reviewer can allow it in restrict.json.
                    reason = "qr_not_located"
                elif rejected:
                    print(
                        f"  ! {path.name} p.{page_no}: {len(rejected)} QR-like area(s) ignored as noise; check the image"
                    )
                # The CUIT printed on the invoice must be blacked out too. OCR may misread a digit
                # (so the text mask misses it), but the QR gives it exactly: look for it on the page.
                for f in found:
                    fields = qr.parse_arca(f.payload)
                    cuit = str(fields["cuit"]) if fields and fields.get("cuit") else ""
                    if len(cuit) != 11 or cuit[:2] not in redact.PERSON_CUIT_PREFIXES:
                        continue
                    hits = [h for form in (cuit, f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}", f"{cuit[:2]} {cuit[2:10]} {cuit[10]}")
                            for h in page.search_for(form)]  # fmt: skip
                    rects += hits
                    if (
                        not hits
                        and reason is None
                        and re.search(r"C\.?\s?U\.?\s?I\.?\s?T", "\n".join(visible), re.I)
                    ):
                        reason = (
                            "unlocated_identifier"  # a CUIT is printed but we cannot find the person's one
                        )

            if kind == "comprobantes" and (i in scanned or mixed):
                # A photo or scan: OCR may not even read the word "CUIT", so a person's number
                # can survive masking. Published only after someone checked the image.
                if page_no not in checked:
                    reason = reason or "unchecked_scan"
                elif reason in ("no_text", "qr_not_located", "unlocated_identifier"):
                    # Unreadable for OCR, a QR the detector missed, or a number masked in the text
                    # but not found on the image: a person looked at the image and listed what
                    # to black out (the QR or number included).
                    reason = None

            unredacted = page_no in ov.full and page_no not in ov.restrict
            if page_no in ov.restrict:
                reason = "manual"
            elif page_no in ov.allow or unredacted:
                reason = None
            if unredacted:
                rects, hidden, strings = [], set(), []
                visible = list(row_texts)
                (out / "raw" / f"p{page_no:03d}.txt").write_text("\n".join(visible))

            rec = PageRecord(
                page_no=page_no,
                text="" if reason else ("\n".join(visible) if unredacted else (redact.redact_text("\n".join(visible)) or "")),
                ocr_engine="none"
                if not any(row_texts)
                else ("tesseract" if i in scanned or mixed else "pdf-text"),
                has_qr=has_qr,
                restricted=reason is not None,
                restricted_reason=reason,
                hidden_lines=len(hidden),
                redacted_strings=len(strings),
            )
            manifest.pages.append(rec)
            plans.append((rec, rects))

    if kind == "comprobantes":
        (out / "raw" / "qr.json").write_text(json.dumps(qr_payloads, indent=1))
    manifest.period = guess_period(path.name, (out / "raw" / "p001.txt").read_text())
    manifest.title = _title(kind, manifest.period, path)

    public = out / "public.pdf"
    build_public_pdf(src, public, plans)
    with pymupdf.open(public) as doc:
        for rec in manifest.pages:
            if not rec.restricted:
                pix = doc[rec.page_no - 1].get_pixmap(dpi=RENDER_DPI)
                pix.pil_save(out / f"p{rec.page_no:03d}.webp", format="WEBP", quality=WEBP_QUALITY)

    mpath.write_text(manifest.model_dump_json(indent=2))
    return manifest


def inbox_files() -> list[tuple[Path, str]]:
    """(path, kind) for every PDF in data/inbox/<kind folder>/ and in data/inbox/ itself,
    plus the photos in data/inbox/actas/."""
    from .actas import IMAGE_SUFFIXES

    found: list[tuple[Path, str]] = []
    for folder, kind in KIND_MAP.items():
        d = INBOX / folder
        if d.is_dir():
            found += [(p, kind) for p in sorted(d.glob("*.pdf"))]
            if kind == "acta":  # photos of the handwritten book (actas.py)
                found += [(p, kind) for p in sorted(d.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES]
    found += [(p, classify_name(p.name)) for p in sorted(INBOX.glob("*.pdf"))]
    return found


def ingest_all(force: bool = False) -> list[DocumentManifest]:
    manifests = []
    files = inbox_files()
    load_overrides({sha256_file(p)[:16] for p, _ in files})  # validate before doing any work
    seen: set[str] = set()
    for path, kind in files:
        sha = sha256_file(path)
        if sha in seen:
            print(f"  skip {kind:12} {path.name} (same content as a file already listed)")
            continue
        seen.add(sha)
        if kind not in PHASE_KINDS:
            print(f"  skip {kind:12} {path.name} (not in this phase)")
            continue
        if kind == "acta":
            from .actas import ingest_pdf, ingest_photo

            m = ingest_pdf(path, force=force) if path.suffix.lower() == ".pdf" else ingest_photo(path, force=force)
            todo = sum(1 for p in m.pages if p.restricted)
            print(f"  {kind:12} {path.name}: {m.title}" + (f", {todo} pages private" if todo else ""))
            manifests.append(m)
            continue
        m = ingest_file(path, kind, force=force)
        reasons: dict[str, int] = {}
        for p in m.pages:
            if p.restricted_reason:
                reasons[p.restricted_reason] = reasons.get(p.restricted_reason, 0) + 1
        hidden = sum(1 for p in m.pages if p.hidden_lines or p.redacted_strings)
        notes = [f"{n} restricted ({r})" for r, n in reasons.items()]
        if hidden:
            notes.append(f"{hidden} with blacked-out areas")
        print(f"  {kind:12} {path.name}: {len(m.pages)} pages" + (f", {', '.join(notes)}" if notes else ""))
        manifests.append(m)
    return manifests


def load_manifests() -> list[DocumentManifest]:
    return [
        DocumentManifest.model_validate_json(p.read_text())
        for p in sorted((WORK / "docs").glob("*/manifest.json"))
    ]


def raw_text(manifest: DocumentManifest, page_no: int) -> str:
    return (doc_dir(manifest) / "raw" / f"p{page_no:03d}.txt").read_text()
