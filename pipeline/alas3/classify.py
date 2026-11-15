"""Step 5: rule-based classification from taxonomy.yaml (LLM leftovers: Phase 2)."""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path

import yaml

from .schemas import Liquidacion

TAXONOMY = Path(__file__).resolve().parents[1] / "taxonomy.yaml"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


@cache
def _rules(path: Path = TAXONOMY) -> list[tuple[str, re.Pattern[str], list[str]]]:
    data = yaml.safe_load(path.read_text())
    rules = []
    for r in data["subcategorias"]:
        # Whole words (plus Spanish plurals): "gas" must not match "gastos", "taxi" matches "taxis".
        alts = "|".join(re.escape(_norm(k).strip()) for k in r["keywords"])
        rules.append((r["name"], re.compile(rf"\b(?:{alts})(?:e?s)?\b"), r.get("tags", [])))
    return rules


def classify_text(text: str) -> tuple[str | None, list[str]]:
    t = _norm(text)
    for name, pattern, tags in _rules():
        if pattern.search(t):
            return name, tags
    return None, []


def classify_liquidacion(liq: Liquidacion) -> Liquidacion:
    for line in liq.lines:
        if line.subcategoria is None:
            line.subcategoria, _ = classify_text(
                f"{line.concepto} {line.detalle or ''} {line.proveedor or ''}"
            )
    return liq
