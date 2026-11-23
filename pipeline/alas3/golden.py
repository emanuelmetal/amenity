"""Field accuracy of the receipt transcriptions against a hand-checked golden set.

PLAN.md Phase 2 is done when transcribed receipts reach >= 90% field accuracy. The golden
set lives in data/work/golden.json (real data, git-ignored): pages re-read by a person, each
with the receipts it shows and only the fields the page shows unambiguously:

    {"pages": [{"sha16": "...", "page": 12,
                "receipts": [{"total": 4100.0, "fecha": "2025-07-07", "pto_vta": 6, "nro_cmp": 18730}]}]}

Each golden receipt is paired with the extracted receipt on that page whose total is closest
(so a page with several recibos is scored receipt by receipt); a receipt nobody extracted
counts every one of its fields as wrong. QR-read fields are exact by construction, so the set
should hold transcribed (non-QR) receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import WORK

GOLDEN_FILE = WORK / "golden.json"
FIELDS = ("total", "fecha", "pto_vta", "nro_cmp")
THRESHOLD = 0.90


@dataclass
class Score:
    checked: int = 0
    correct: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.checked if self.checked else 1.0


def _same(fld: str, want, got) -> bool:
    if fld == "total":
        return got is not None and abs(float(got) - float(want)) <= 0.01
    return got == want


def evaluate(golden: dict, tickets_by_page: dict[tuple[str, int], list[dict]]) -> Score:
    """`tickets_by_page`: (sha16, page) -> extracted receipts (dicts) that include that page."""
    score = Score()
    for pg in golden.get("pages", []):
        pool = list(tickets_by_page.get((pg["sha16"], pg["page"]), []))
        for want in pg["receipts"]:
            got = min(pool, key=lambda t: abs((t.get("total") or 0) - want["total"]), default=None)
            if got is not None:
                pool.remove(got)  # each extracted receipt answers one golden receipt
            for fld in FIELDS:
                if fld not in want:
                    continue
                score.checked += 1
                value = got.get(fld) if got else None
                if _same(fld, want[fld], value):
                    score.correct += 1
                else:
                    score.misses.append(f"{pg.get('bundle', pg['sha16'])} p.{pg['page']} {fld}: esperado {want[fld]!r}, extraído {value!r}")
    return score


def run(golden_file: Path = GOLDEN_FILE) -> Score | None:
    """Score the current extraction; None when there is no golden set."""
    if not golden_file.exists():
        return None
    from .extract import load_extract
    from .ingest import load_manifests
    from .schemas import Comprobantes

    golden = json.loads(golden_file.read_text())
    wanted = {pg["sha16"] for pg in golden.get("pages", [])}
    by_page: dict[tuple[str, int], list[dict]] = {}
    for m in load_manifests():
        sha16 = m.sha256[:16]
        if sha16 not in wanted:
            continue
        ext = load_extract(m)
        if not isinstance(ext, Comprobantes):
            continue
        for t in ext.tickets:
            for p in t.page_nos:
                by_page.setdefault((sha16, p), []).append(t.model_dump())
    return evaluate(golden, by_page)
