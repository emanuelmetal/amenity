"""Step 3: QR codes on receipt pages (PLAN.md §4.3).

ARCA/AFIP electronic invoices carry a QR whose URL embeds the invoice data:
  https://www.afip.gob.ar/fe/qr/?p=<base64 JSON>   (also www.arca.gob.ar, and the older
  https://serviciosweb.afip.gob.ar/genericos/comprobantes/cae.aspx?p=...)
  {"ver":1,"fecha":"2026-01-15","cuit":20123456789,"ptoVta":2,"tipoCmp":11,
   "nroCmp":2707,"importe":48000,"moneda":"PES",...}
Those fields are exact (no OCR guesswork).

Every QR found on a page, decoded or not, is also blacked out in public.pdf:
an invoice QR encodes the issuer's CUIT, which for monotributo vendors is a
person's CUIL (see ingest.py).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pymupdf

_ARCA_HOST = re.compile(r"(^|\.)(afip|arca)\.gob\.ar$", re.I)
_LEADING_ZEROS = re.compile(r"([:,\[]\s*)0+(\d)")
# Render resolutions tried in order; small QRs on scans need the higher one.
DPIS = (150, 300)
RETRY_DPIS = (400, 600)  # invoice pages whose QR was not decoded: slower, finds small or blurry ones
MAX_ROUNDS = 6  # detect -> mask -> detect again, per resolution


@dataclass
class FoundQR:
    payload: str | None  # None: located but not decodable
    rect: pymupdf.Rect  # unrotated page coordinates, padded


def _detectors():
    import cv2

    return [cv2.QRCodeDetector(), cv2.QRCodeDetectorAruco()]


def _gray(page: pymupdf.Page, dpi: int):
    import numpy as np

    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w).copy()


def _to_rect(page: pymupdf.Page, pts, dpi: int, pad: float = 4.0) -> pymupdf.Rect:
    scale = 72.0 / dpi
    xs = [float(x) * scale for x, _ in pts]
    ys = [float(y) * scale for _, y in pts]
    r = pymupdf.Rect(min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)
    return r * page.derotation_matrix  # pixmaps show the rotated page; annotations use unrotated coords


def find_qr(
    page: pymupdf.Page, rejected: list[pymupdf.Rect] | None = None, dpis: tuple[int, ...] = DPIS
) -> list[FoundQR]:
    """All QR codes on the page: decoded payloads plus located-only ones.

    Every resolution and detector always runs: stopping once the codes found so far are
    decoded would miss a small second QR (a second receipt on the page) that only shows
    up at the higher resolution, and every QR must be blacked out.

    Located-only detections that don't look like a QR (see plausible_qr) are skipped;
    they are appended to `rejected` so the caller can fail closed on an invoice page.
    """
    found: list[FoundQR] = []

    def add(val: str | None, pts, dpi: int) -> None:
        rect = _to_rect(page, pts, dpi)
        if not val and not plausible_qr(page, rect):
            # A located-only "QR" the size of half the page is usually noise (handwriting,
            # table lines), but it could be a large or skewed real one: report it.
            if rejected is not None and not any(overlap(rect, r) for r in rejected):
                rejected.append(rect & page.mediabox)
            return
        rect &= page.mediabox  # never black out beyond the page
        for f in found:
            if overlap(rect, f.rect):
                f.payload = f.payload or val or None  # same code seen again: keep the decoded version
                return
        found.append(FoundQR(payload=val or None, rect=rect))

    import numpy as np

    for dpi in dpis:
        img = _gray(page, dpi)
        # A large code can hide a small one from the detectors: paint every code found
        # white and search again, until a round finds nothing new.
        for _ in range(MAX_ROUNDS):
            hits: list[tuple[str | None, object]] = []
            for det in _detectors():
                ok, values, points, _ = det.detectAndDecodeMulti(img)
                if ok and points is not None:
                    hits += list(zip(values, points, strict=False))
                # Single-code detector as a fallback: it locates some damaged codes the multi one misses.
                ok1, pts1 = det.detect(img)
                if ok1 and pts1 is not None:
                    hits.append((None, pts1.reshape(-1, 2)))
            if not hits:
                break
            for val, pts in hits:
                add(val, pts, dpi)
                p = np.asarray(pts, dtype=float).reshape(-1, 2)
                x0, y0 = np.maximum(p.min(axis=0) - 8, 0).astype(int)
                x1, y1 = (p.max(axis=0) + 8).astype(int)
                img[y0:y1, x0:x1] = 255
    return found


# Text that marks an electronic invoice, which must carry a QR.
ARCA_MARKERS = re.compile(r"(?i)\bC\.?\s?A\.?\s?E\.?\b|comprobante\s+autorizado")


# A located-but-undecoded detection is only trusted when it looks like an invoice QR:
# roughly square and small. Real ones on these receipts are 10-15% of the page width.
QR_MAX_SIDE = 0.3  # share of the page's shorter side
QR_MIN_SIDE = 0.02


def plausible_qr(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    short = min(page.mediabox.width, page.mediabox.height)
    w, h = rect.width, rect.height
    if not (
        QR_MIN_SIDE * short <= w <= QR_MAX_SIDE * short and QR_MIN_SIDE * short <= h <= QR_MAX_SIDE * short
    ):
        return False
    return 0.6 <= w / h <= 1.6


def overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    inter = pymupdf.Rect(a) & b
    return not inter.is_empty and inter.get_area() > 0.5 * min(a.get_area(), b.get_area())


def _digits(v: object) -> str:
    """A numeric code as digits. Some issuers write it as a JSON float (8.6e13 -> '86...629.0')."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if not s.isdigit():
        raise ValueError(f"not a numeric code: {s!r}")
    return s


def parse_arca(payload: str | None) -> dict | None:
    """Invoice fields from an ARCA/AFIP invoice QR URL, or None for any other QR."""
    if not payload:
        return None
    try:
        u = urlparse(payload.strip())
    except ValueError:
        return None
    if not _ARCA_HOST.search(u.hostname or "") or not ("/fe/qr" in u.path or u.path.endswith("/cae.aspx")):
        return None
    p = parse_qs(u.query).get("p", [""])[0].strip()
    if not p:
        return None
    try:
        raw = base64.urlsafe_b64decode(p.replace("+", "-").replace("/", "_") + "=" * (-len(p) % 4))
        # Some issuers write numbers with leading zeros ("nroCmp":00006036), which is not valid JSON.
        text = _LEADING_ZEROS.sub(r"\1\2", raw.decode("utf-8", "replace"))
        data = json.loads(text)
    except (binascii.Error, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return {
            "fecha": str(data["fecha"])[:10],
            "cuit": _digits(data["cuit"]),
            "pto_vta": int(data["ptoVta"]),
            "tipo_cmp": int(data["tipoCmp"]),
            "nro_cmp": int(data["nroCmp"]),
            "total": float(data["importe"]),
            "cae": _digits(data["codAut"]) if data.get("codAut") else None,
        }
    except (KeyError, TypeError, ValueError):
        return None


# ARCA voucher type codes -> (kind, letter). Only the common ones; others map to "otro".
TIPO_CMP = {
    1: ("factura", "A"), 6: ("factura", "B"), 11: ("factura", "C"), 51: ("factura", "M"),
    4: ("recibo", "A"), 9: ("recibo", "B"), 15: ("recibo", "C"),
    3: ("nota_credito", "A"), 8: ("nota_credito", "B"), 13: ("nota_credito", "C"),
    2: ("nota_debito", "A"), 7: ("nota_debito", "B"), 12: ("nota_debito", "C"),
    81: ("ticket", "A"), 82: ("ticket", "B"), 83: ("ticket", None),
}  # fmt: skip


def find_barcodes(page: pymupdf.Page, dpi: int = 200) -> list[pymupdf.Rect]:
    """1D barcodes on the page. Older AFIP invoices encode the issuer's CUIT (a person's
    CUIL for monotributo vendors) in an interleaved 2-of-5 barcode, so receipts lose them
    all, like QR codes."""
    import cv2
    import numpy as np

    img = _gray(page, dpi)
    det = cv2.barcode.BarcodeDetector()
    rects: list[pymupdf.Rect] = []
    for _ in range(MAX_ROUNDS):
        ok, points = det.detect(img)
        if not ok or points is None or not len(points):
            break
        for pts in points:
            p = np.asarray(pts, dtype=float).reshape(-1, 2)
            rects.append(_to_rect(page, p, dpi, pad=6.0))
            x0, y0 = np.maximum(p.min(axis=0) - 8, 0).astype(int)
            x1, y1 = (p.max(axis=0) + 8).astype(int)
            img[y0:y1, x0:x1] = 255
    return rects
