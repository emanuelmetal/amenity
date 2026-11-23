"""Phase 3: the minutes book (actas), photographed page by page.

Inputs: data/inbox/actas/*.jpeg|jpg|png, one photo per folio of the handwritten book.
Each photo becomes its own 1-page document (kind 'acta', id from the image hash), so
adding photos later never changes the ids of the ones already published.

Owner decision (2026-11-23): the photos are published as photographed, with nothing
blacked out (names, units and signatures stay visible). The image is re-encoded (drops
EXIF/GPS metadata) and wrapped in a 1-page PDF that is both the original and public.pdf.

Handwriting is not OCR'd: Claude Code reads the photos and writes the transcription to
data/work/extract/actas.json (schemas.ActaBook): the text of every folio (people by role
only) and the actas found in it, which may cross folios. A folio not transcribed yet is
`restricted` ("untranscribed") and reported by `alas3 ingest`.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from .config import RENDER_DPI, WEBP_QUALITY, WORK
from .redact import redact_text
from .schemas import ActaBook, DocumentManifest, PageRecord

BOOK_FILE = WORK / "extract" / "actas.json"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def load_book(path: Path | None = None) -> ActaBook:
    path = path or BOOK_FILE
    if not path.exists():
        return ActaBook()
    try:
        return ActaBook.model_validate_json(path.read_text())
    except ValueError as e:  # fails loudly: a half-read book must not be published
        raise SystemExit(f"{path}: invalid transcription:\n{e}") from e


def _photo_pdf(src: Path, dest: Path) -> None:
    """The photo, upright and without metadata, as a 1-page PDF sized so that rendering it
    at RENDER_DPI gives back the photo's own pixels."""
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.info = {}  # the JPEG comment (COM) would otherwise be written back
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90)  # no exif= argument: metadata is dropped
        w, h = im.size
    doc = pymupdf.open()
    page = doc.new_page(width=w * 72 / RENDER_DPI, height=h * 72 / RENDER_DPI)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.set_metadata({})
    doc.save(dest, garbage=4, deflate=True)
    doc.close()


def ingest_photo(path: Path, force: bool = False, book: ActaBook | None = None) -> DocumentManifest:
    """Cheap (no OCR), so the manifest is rebuilt on every run: the transcription decides
    the page text and whether the folio is published."""
    from .ingest import _doc_id, doc_dir, load_overrides, sha256_file

    book = book if book is not None else load_book()
    sha = sha256_file(path)
    m = DocumentManifest(id=_doc_id(sha), kind="acta", title="", source_name=path.name, sha256=sha)
    out = doc_dir(m)
    out.mkdir(parents=True, exist_ok=True)
    photo = out / "photo.pdf"  # private until the folio is transcribed
    if force or not photo.exists():
        _photo_pdf(path, photo)

    folio = book.folios.get(m.work_dir_name)
    ov = load_overrides().get(m.work_dir_name)
    # restrict.json withholds a folio whatever the transcription says (e.g. it shows a DNI or a debt list).
    reason = "manual" if ov and 1 in ov.restrict else (None if folio else "untranscribed")
    public = out / "public.pdf"
    webp = out / "p001.webp"
    if reason:
        # The document row is still published (its page restricted): its PDF must be blank.
        webp.unlink(missing_ok=True)  # a restricted page never keeps a render around
        with pymupdf.open(photo) as src:
            blank = pymupdf.open()
            page = blank.new_page(width=src[0].rect.width, height=src[0].rect.height)
            page.insert_text((36, 72), "Folio no publicado.", fontsize=12)
            blank.set_metadata({})
            data = blank.tobytes(garbage=4, deflate=True, no_new_id=True)
            blank.close()
        if not public.exists() or public.read_bytes() != data:  # stable bytes: no re-upload on every publish
            public.write_bytes(data)
        m.title = "Libro de actas (foto sin transcribir)" if reason == "untranscribed" else "Libro de actas (folio no publicado)"
    else:
        assert folio is not None
        if force or not public.exists() or public.read_bytes() != photo.read_bytes():
            public.write_bytes(photo.read_bytes())
            webp.unlink(missing_ok=True)
        if not webp.exists():
            with pymupdf.open(public) as doc:
                doc[0].get_pixmap(dpi=RENDER_DPI).pil_save(webp, format="WEBP", quality=WEBP_QUALITY)
        m.title = f"Libro de actas, folio {folio.folio}"
    m.pages.append(
        PageRecord(
            page_no=1,
            text="" if reason else (redact_text(folio.texto) or ""),
            ocr_engine="none" if reason else "manual",
            restricted=reason is not None,
            restricted_reason=reason,
        )
    )
    (out / "manifest.json").write_text(m.model_dump_json(indent=2))
    return m


def folio_key(m: DocumentManifest, page_no: int) -> str:
    """Key of a published page in ActaBook.folios."""
    return m.work_dir_name if m.source_name.lower().endswith(IMAGE_SUFFIXES) else f"{m.work_dir_name}#{page_no}"


def ingest_pdf(path: Path, force: bool = False, book: ActaBook | None = None) -> DocumentManifest:
    """A scanned acta (e.g. an asamblea's notarial testimony). Every page is private until it is
    transcribed (`<sha16>#<page>` in the book); its `checked` areas are blacked out (pixels);
    `restrict.json` still wins. No OCR: the transcription is the text."""
    from .ingest import _doc_id, build_public_pdf, doc_dir, load_overrides, sha256_file

    book = book if book is not None else load_book()
    sha = sha256_file(path)
    m = DocumentManifest(id=_doc_id(sha), kind="acta", title="", source_name=path.name, sha256=sha)
    out = doc_dir(m)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("p*.webp"):
        old.unlink()
    ov = load_overrides().get(m.work_dir_name)
    plans: list[tuple[PageRecord, list[pymupdf.Rect]]] = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            n = i + 1
            folio = book.folios.get(f"{m.work_dir_name}#{n}")
            reason = "manual" if ov and n in ov.restrict else (None if folio else "untranscribed")
            rects = []
            if folio and not reason:
                w, h = page.rect.width, page.rect.height
                for b in folio.checked:
                    shown = pymupdf.Rect(b.x0 * w, b.y0 * h, b.x1 * w, b.y1 * h)
                    rects.append((shown * page.derotation_matrix) & page.mediabox)
            rec = PageRecord(
                page_no=n,
                text="" if reason else (redact_text(folio.texto) or ""),
                ocr_engine="none" if reason else "manual",
                restricted=reason is not None,
                restricted_reason=reason,
                redacted_strings=len(rects),
            )
            m.pages.append(rec)
            plans.append((rec, rects))
    public = out / "public.pdf"
    build_public_pdf(path, public, plans)
    with pymupdf.open(public) as doc:
        for rec in m.pages:
            if not rec.restricted:
                doc[rec.page_no - 1].get_pixmap(dpi=RENDER_DPI).pil_save(
                    out / f"p{rec.page_no:03d}.webp", format="WEBP", quality=WEBP_QUALITY
                )
    m.title = book.titulos.get(m.work_dir_name) or "Acta (sin transcribir)"
    (out / "manifest.json").write_text(m.model_dump_json(indent=2))
    return m


def report(manifests: list[DocumentManifest], book: ActaBook | None = None) -> list[str]:
    """Lines for `alas3 ingest`: photos to transcribe and the actas found."""
    book = book if book is not None else load_book()
    docs = [m for m in manifests if m.kind == "acta"]
    known = {folio_key(m, p.page_no) for m in docs for p in m.pages}
    out = [f"  actas: {len(book.actas)} actas over {len(book.folios)} transcribed pages"]
    for m in docs:
        for p in m.pages:
            if p.restricted_reason == "untranscribed":
                out.append(f"    to transcribe: {folio_key(m, p.page_no)}  {m.source_name} p.{p.page_no}")
    for key in book.folios:
        if key not in known:
            out.append(f"    ! transcribed page {key} has no file in data/inbox/actas/")
    return out
