"""Liquidación de expensas parser (layout-text based).

Tuned on the administrator's "Resumen de cuenta" (ResumenGastos_MMYYYY.pdf),
one page per month:

    Total de Gastos del Mes  1.234.567,89            <- summary block, AR number format
    DETALLE DE LOS GASTOS AL MES: ENERO DE 2026
    Concepto Gastos  Detalle Gastos  Gastos
    SUELDOS Y JORNALES                                 <- rubro: upper-case line, no amount
    SUELDO ENCARGADO  mes 01/2026  1,000,000.00  <- concepto  detalle  importe (US format!)
    ...
    Total de Gastos del Período: 01/2026  1,234,567.89
    FONDO DE OBRA ...                                  <- ignored
    Unidades con deudas ...                            <- never parsed (and hidden by redact.page_policy)

The older generic layout ("RUBRO 1 - X" ... "TOTAL RUBRO 1") is still accepted.
Lines get confidence 0.8 and verified=False ("Sin verificar" until reviewed).
"""

from __future__ import annotations

import re

from .redact import _DEBT_START
from .schemas import Liquidacion, LiquidacionLine, RubroTotal

# 1.234,56 (AR) or 1,234.56 (US), optional sign/$ /parentheses.
AMOUNT = r"-?\$?\s?\(?-?(?:\d{1,3}(?:[.,]\d{3})+|\d+)[.,]\d{2}\)?"
_AMOUNT_AT_END = re.compile(rf"^(?P<text>.*?)\s{{2,}}(?P<amount>{AMOUNT})\s*$")
_DETAIL_START = re.compile(r"(?i)^\s*detalle\s+de\s+los\s+gastos")
_COLUMN_HEADER = re.compile(r"(?i)^\s*concepto\b.*\bgastos?\s*$")
_RUBRO_HEADER = re.compile(r"^\s*RUBRO\s+(?P<n>\d+)\s*[-.:–]?\s*(?P<name>.*?)\s*$", re.I)
_RUBRO_TOTAL = re.compile(r"^\s*(SUB\s*)?TOTAL\s+(DEL\s+)?RUBRO\b", re.I)
_GRAND_TOTAL = re.compile(
    r"(?i)^\s*TOTAL\s+(GENERAL|DE\s+GASTOS(\s+DEL\s+(MES|PER[IÍ]ODO))?|GASTOS(\s+DEL\s+MES)?|EGRESOS|A\s+PRORRATEAR)\b"
)
# After the expense detail: other ledgers we don't parse as expenses.
_DETAIL_END = re.compile(
    r"(?i)^\s*(fondo\s+de\s+(obra|reserva)|unidades\s+(con\s+deudas?|en\s+mora)|total\s+expensas)"
)
_CUIT = re.compile(r"\b(3[034])-?\d{8}-?\d\b")


def parse_amount(s: str) -> float:
    s = s.strip()
    neg = s.startswith("-") or "(" in s or "$-" in s.replace(" ", "")
    digits = re.sub(r"[^\d.,]", "", s)
    # The last separator followed by exactly two digits is the decimal one.
    if len(digits) >= 3 and digits[-3] in ".,":
        v = float(re.sub(r"[.,]", "", digits[:-3]) + "." + digits[-2:])
    else:
        v = float(re.sub(r"[.,]", "", digits))
    return -v if neg else v


def _is_rubro_header(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.9


def parse(period: str, pages: list[tuple[int, str]]) -> Liquidacion:
    lines: list[LiquidacionLine] = []
    rubro_totals: list[RubroTotal] = []
    total: float | None = None
    rubro: str | None = None
    has_detail_marker = any(_DETAIL_START.search(t) for _, t in pages)
    in_detail = not has_detail_marker  # generic layout: the whole document is detail

    for page_no, text in pages:
        for raw in text.splitlines():
            if not raw.strip():
                continue
            if _DETAIL_START.search(raw):
                in_detail = True
                continue
            am = _AMOUNT_AT_END.match(raw)
            label = am.group("text").strip() if am else raw.strip()
            if am and _GRAND_TOTAL.match(label):
                # The detail's own total wins over the summary block's.
                total = parse_amount(am.group("amount"))
                if has_detail_marker and in_detail:
                    in_detail = False
                continue
            if not in_detail or _COLUMN_HEADER.match(raw):
                continue
            if _DETAIL_END.match(raw) or _DEBT_START.search(raw):
                in_detail = False
                continue

            hm = _RUBRO_HEADER.match(raw)
            if hm and not am:
                name = hm.group("name").strip(" -.:").capitalize() or f"Rubro {hm.group('n')}"
                rubro = f"{hm.group('n')}. {name}"
                continue
            if not am:
                if _is_rubro_header(raw):
                    rubro = raw.strip().rstrip(".").capitalize()
                continue
            amount = parse_amount(am.group("amount"))
            if _RUBRO_TOTAL.match(label):
                if rubro:
                    rubro_totals.append(RubroTotal(rubro=rubro, total=amount))
                continue
            if rubro is None:
                continue  # amounts before the first rubro are ignored

            cells = [c.strip() for c in re.split(r"\s{2,}", label) if c.strip()]
            cuit = _CUIT.search(label)
            lines.append(
                LiquidacionLine(
                    rubro=rubro,
                    concepto=cells[0] if cells else label,
                    detalle="  ".join(cells[1:]) or None,
                    cuit=cuit.group(0) if cuit else None,
                    importe=amount,
                    page_no=page_no,
                    confidence=0.8,
                )
            )
    return Liquidacion(period=period, total=total, rubro_totals=rubro_totals, lines=lines)
