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
# Phase 3 adds "acta". Anything else is never published.
PHASE_KINDS = ("reglamento", "liquidacion", "comprobantes")

# The consortium's ejercicio runs September to August (the administrator's yearly balances,
# data/inbox/balances/). NB: the Reglamento de Copropiedad, art. 15, says January–December.
EJERCICIO_START_MONTH = 9


def ejercicio(period: str) -> str:
    """First month of the ejercicio a "YYYY-MM" month belongs to: 2026-03 -> "2025-09"."""
    y, m = map(int, period.split("-"))
    return f"{y if m >= EJERCICIO_START_MONTH else y - 1}-{EJERCICIO_START_MONTH:02d}"


RENDER_DPI = 150
WEBP_QUALITY = 70
# A page with fewer extractable characters than this is treated as a scan.
MIN_TEXT_CHARS = 40
# Page ids are document_id * PAGE_ID_FACTOR + page_no (stable across runs).
PAGE_ID_FACTOR = 10_000
