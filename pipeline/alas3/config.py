"""Paths and constants. Everything under data/ is personal data and git-ignored."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("ALAS3_DATA", REPO / "data"))
INBOX = DATA / "inbox"
WORK = DATA / "work"
OUT = DATA / "out"
WEB = REPO / "web"
DB_NAME = "torre3"
BUCKET = "torre3-files"

KINDS = ("liquidaciones", "comprobantes", "reglamento", "actas", "otro")
# inbox folder -> documents.kind
KIND_MAP = {
    "liquidaciones": "liquidacion",
    "comprobantes": "comprobantes",
    "reglamento": "reglamento",
    "actas": "acta",
    "otro": "otro",
}

# Document kinds processed and published in the current phase (PLAN.md §10).
# Phase 2 adds "comprobantes", Phase 3 "acta". Anything else is never published.
PHASE_KINDS = ("reglamento", "liquidacion")

RENDER_DPI = 150
WEBP_QUALITY = 70
# A page with fewer extractable characters than this is treated as a scan.
MIN_TEXT_CHARS = 40
# Page ids are document_id * PAGE_ID_FACTOR + page_no (stable across runs).
PAGE_ID_FACTOR = 10_000
