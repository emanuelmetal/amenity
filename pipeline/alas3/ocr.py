"""OCR for scanned pages via the OCRmyPDF CLI (Tesseract `spa`).

Born-digital pages are left untouched (--skip-text). The result is cached.
PaddleOCR fallback for hard tickets is Phase 2.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ocr_document(src: Path, dest: Path) -> Path | None:
    if dest.exists():
        return dest
    if not shutil.which("ocrmypdf"):
        print("  ! ocrmypdf not installed: scanned pages keep no text (brew install ocrmypdf tesseract-lang)")
        return None
    cmd = [
        "ocrmypdf",
        "-l",
        "spa",
        "--skip-text",
        "--deskew",
        "--rotate-pages",
        "--optimize",
        "1",
        "--output-type",
        "pdf",
        str(src),
        str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ! OCR failed for {src.name}: {res.stderr.strip().splitlines()[-1:]}")
        return None
    return dest


def ocr_page_pixels(page) -> str:
    """Tesseract on the rendered page, for checking what embedded images show.

    Returns "" when Tesseract is unavailable; callers treat images they cannot read
    as unchecked (see ingest: such mixed pages still go through the text policy).
    """
    import tempfile

    if not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "page.png"
        page.get_pixmap(dpi=200).save(png)
        res = subprocess.run(["tesseract", str(png), "stdout", "-l", "spa"], capture_output=True, text=True)
        return res.stdout if res.returncode == 0 else ""
