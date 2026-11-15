"""Privacy redaction (PLAN.md §4.8, §8). SECURITY/PRIVACY CRITICAL.

Three mechanisms, all fail-closed:

1. `redact_text`: masks personal identifiers (person CUIL/CUIT, DNI, CBU/CVU)
   in every string that gets published (page text, expense lines, articles).
2. `page_policy`: decides per page
   - `restricted`: the whole page is never served nor indexed (payroll slips,
     pages that are mostly a debt list, scanned pages without readable text);
   - `hidden_lines`: a block of lines (e.g. "Unidades en mora" at the bottom
     of a liquidación) that is blacked out in the image/PDF and dropped from
     the published text, while the rest of the page stays visible.
3. `sensitive_strings`: exact identifier strings to black out in the PDF and
   the rendered image (see ingest.redacted_pdf).

Company CUITs (prefixes 30, 33, 34) are kept: vendors are public information
and are needed for matching. Person CUIL/CUITs (20, 23, 24, 27) are masked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MASK = "[oculto]"

# 22-digit CBU/CVU, optionally separated by spaces/dashes.
_CBU = re.compile(r"(?<!\d)(?:\d[ \-]?){21}\d(?!\d)")
# CUIT/CUIL: 2-8-1 digits with optional separators.
_CUIT = re.compile(r"(?<!\d)(\d{2})[ \-.]?(\d{8}|\d{2}\.\d{3}\.\d{3})[ \-.]?(\d)(?!\d)")
# Labelled CUIL/CUIT, tolerant to spaced separators ("CUIL 20 - 12345678 - 9"). A CUIL label is
# masked whatever the prefix (OCR may misread it); a CUIT label only for person prefixes.
_CUIT_LABELED = re.compile(
    r"(?i)\b(C\.?\s?U\.?\s?I\.?\s?([LT])\.?)(\s*(?:n[°ºo.]*)?\s*:?\s*)(\d{2}\s*[-.]?\s*\d{8}\s*[-.]?\s*\d)(?!\d)"
)
# DNI after a label (dotted, spaced or plain), or in dotted form NN.NNN.NNN.
_DNI_LABELED = re.compile(
    r"(?i)\b(D\.?\s?N\.?\s?I\.?|D\.?\s?U\.?|M\.?\s?I\.?|documento(?:\s+nacional\s+de\s+identidad)?|doc\.|L\.?\s?E\.?|L\.?\s?C\.?)"
    r"(\s*(?:n[°ºo.]*\s*:?|nro\.?\s*:?|:)?\s*)(\d{1,2}[. ]?\d{3}[. ]?\d{3})\b"
)
_DNI_DOTTED = re.compile(r"(?<![\d.,$])(?<!\$ )\d{1,2}\.\d{3}\.\d{3}(?![\d.,])")

PERSON_CUIT_PREFIXES = {"20", "23", "24", "27"}

PAYROLL_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"recibo\s+de\s+(haberes|sueldo)",
        r"\bF\.?\s?931\b",
        r"liquidaci[oó]n\s+de\s+haberes",
        r"sueldo\s+b[aá]sico",
        r"aportes\s+jubilatorios",
        r"\bSUTERH\b.*\bhaberes\b",
    )
]

# Start of a per-unit debt listing (morosos), hidden by default (§8).
_DEBT_START = re.compile(
    r"(?i)unidades\s+(con\s+deudas?|en\s+mora)|\bmoros[oa]s?\b|\bdeudores\b|saldos?\s+deudor"
    r"|(estado|detalle)\s+de\s+(deudas?|cuentas?)\s+por\s+(unidad|u\.?\s?f)"
)
# Lines that clearly end such a block in the administrator's layout.
_DEBT_END = re.compile(r"(?i)^\s*(vencimiento|horario\s+de\s+atenci|la\s+administraci)")
# One unit ("9/A 901", "UF 12", "U.F. 12", "Dpto 4B") followed by an amount. Counted per
# occurrence, not per line: the administrator prints four units per row.
_UNIT_AMOUNT = re.compile(
    r"(?i)(?:\b\d{1,2}\s?/\s?[A-H]\b(?:\s+\d{2,4})?|\bU\.?\s?F\.?\s?\d+|\bdpto\.?\s?\d+\s?[A-H]?\b)"
    r"[^\d\n]{0,40}\$?\s?\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b"
)
# If this many unit+amount pairs survive outside a hidden block, restrict the whole page.
UNIT_AMOUNTS_RESTRICT = 3


@dataclass
class PagePolicy:
    restricted: str | None = None  # reason, or None
    hidden_lines: set[int] = field(default_factory=set)  # 0-based indexes into the rows passed in
    open_block: bool = False  # a debt block was still open at the end of the page


def _mask_cuit(m: re.Match[str]) -> str:
    return MASK if m.group(1) in PERSON_CUIT_PREFIXES else m.group(0)


def redact_text(text: str | None) -> str | None:
    if not text:
        return text
    text = _CUIT_LABELED.sub(
        lambda m: (
            m.group(0)
            if m.group(2).upper() == "T" and m.group(4)[:2] not in PERSON_CUIT_PREFIXES
            else f"{m.group(1)}{m.group(3)}{MASK}"
        ),
        text,
    )
    text = _CBU.sub(MASK, text)
    text = _CUIT.sub(_mask_cuit, text)
    text = _DNI_LABELED.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    # Dotted 7–8 digit numbers look like DNIs; amounts carry decimals/$ and are excluded by the lookarounds.
    text = _DNI_DOTTED.sub(MASK, text)
    return text


def sensitive_strings(text: str) -> list[str]:
    """The exact substrings `redact_text` would mask (to black out in PDFs/images)."""
    found: list[str] = [
        m.group(4)
        for m in _CUIT_LABELED.finditer(text)
        if m.group(2).upper() == "L" or m.group(4)[:2] in PERSON_CUIT_PREFIXES
    ]
    found += [m.group(0) for m in _CBU.finditer(text)]
    found += [m.group(0) for m in _CUIT.finditer(text) if m.group(1) in PERSON_CUIT_PREFIXES]
    found += [m.group(3) for m in _DNI_LABELED.finditer(text)]
    found += [m.group(0) for m in _DNI_DOTTED.finditer(text)]
    return sorted(set(found), key=len, reverse=True)


def page_policy(rows: str | list[str], *, scanned: bool = False, carry_in: bool = False) -> PagePolicy:
    """Decides what of a page may be published.

    `rows` is the raw (unredacted) text of the page, one entry per layout row; a
    string is split on "\n" only (never str.splitlines, whose extra separators would
    shift the indexes). `scanned` pages need at least MIN_TEXT_CHARS of readable text.
    `carry_in` means the previous page ended inside a debt block.
    """
    from .config import MIN_TEXT_CHARS

    lines = rows.split("\n") if isinstance(rows, str) else list(rows)
    text = "\n".join(lines)
    if len(text.strip()) < (MIN_TEXT_CHARS if scanned else 1):
        # Unreadable scan (OCR missing/failed, photo, stamp only) or empty: nobody can check it.
        return PagePolicy(restricted="no_text" if scanned else None)
    if any(p.search(text) for p in PAYROLL_PATTERNS):
        return PagePolicy(restricted="payroll")

    hidden: set[int] = set()
    in_block = carry_in
    for i, line in enumerate(lines):
        if not in_block and _DEBT_START.search(line):
            in_block = True
        elif in_block and _DEBT_END.search(line):
            in_block = False
        if in_block:
            hidden.add(i)

    stray = sum(len(_UNIT_AMOUNT.findall(ln)) for i, ln in enumerate(lines) if i not in hidden)
    if stray >= UNIT_AMOUNTS_RESTRICT:
        return PagePolicy(restricted="debtors", open_block=in_block)
    visible = [ln for i, ln in enumerate(lines) if i not in hidden and ln.strip()]
    if hidden and len(visible) < 3:
        return PagePolicy(restricted="debtors", open_block=in_block)  # essentially the debt list
    return PagePolicy(hidden_lines=hidden, open_block=in_block)


def restriction_reason(text: str) -> str | None:
    """Back-compat helper: whole-page restriction reason, or None."""
    return page_policy(text).restricted
