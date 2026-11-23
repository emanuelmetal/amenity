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
    FONDO DE OBRA  INGRESOS  EGRESOS                   <- fund ledger (parse_fondo): its outflows
    SALDO INICIAL 'FONDO DE OBRA' AL 10/2026  512.933,19     become lines with fondo=True, kept
    168 MANO DE OBRA TRABAJO DE (Obra explanada)  300.000,00  out of the month's total
    SALDO FINAL 'FONDO DE OBRA' AL 10/2026  212.933,19
    Unidades con deudas ...                            <- never parsed (and hidden by redact.page_policy)

The older generic layout ("RUBRO 1 - X" ... "TOTAL RUBRO 1") is still accepted.
Lines get confidence 0.8 and verified=False ("Sin verificar" until reviewed).
"""

from __future__ import annotations

import re

from .redact import _DEBT_START
from .schemas import Fondo, Liquidacion, LiquidacionLine, Resumen, ResumenItem, RubroTotal

TOLERANCE = 0.01

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


_SUMMARY_HEADER = re.compile(r"(?i)^\s*concepto\s+ingreso\s*/\s*egreso")
_SALDO_INICIAL = re.compile(r"(?i)^\s*saldo\s+inicial\b")
_SALDO_FINAL = re.compile(r"(?i)^\s*saldo\s+final\b")
_PERIOD_TOTALS = re.compile(rf"(?i)\b(?P<kind>INGRESOS|EGRESOS)\s+PER[IÍ]ODO\s*:\s*(?P<amount>{AMOUNT})")


def _split_egresos(items: list[tuple[str, float]], ingresos: float | None) -> set[int]:
    """Indexes of the summary items that are outflows.

    The text layer loses the Ingreso/Egreso column, but the block states the period's
    total income: the items that make up the difference are the outflows (e.g.
    "pasado a fondo de obra", "Gastos Cobranza"). Smallest such subset wins.
    """
    from itertools import combinations

    if ingresos is None:
        return set()
    excess = round(sum(a for _, a in items) - ingresos, 2)
    if abs(excess) <= TOLERANCE:
        return set()
    for k in range(1, min(len(items), 6) + 1):
        for combo in combinations(range(len(items)), k):
            if abs(sum(items[i][1] for i in combo) - excess) <= TOLERANCE:
                return set(combo)
    return set()  # unresolved: validate.check_resumen reports it


def parse_resumen(pages: list[tuple[int, str]]) -> Resumen | None:
    """The "Resumen de cuenta" block above the expense detail."""
    res = Resumen()
    items: list[tuple[str, float]] = []
    in_block = False
    for _, text in pages:
        for raw in text.splitlines():
            if _DETAIL_START.search(raw):
                break
            for m in _PERIOD_TOTALS.finditer(raw):
                v = parse_amount(m.group("amount"))
                if m.group("kind").upper() == "INGRESOS":
                    res.ingresos = v
                else:
                    res.egresos = v
            if _SUMMARY_HEADER.match(raw):
                in_block = True
                continue
            am = _AMOUNT_AT_END.match(raw)
            if not in_block or not am:
                continue
            label, amount = am.group("text").strip(), parse_amount(am.group("amount"))
            if _SALDO_INICIAL.match(label):
                res.saldo_inicial = amount
            elif _SALDO_FINAL.match(label):
                res.saldo_final = amount
                in_block = False
            elif not _GRAND_TOTAL.match(label):  # "Total de Gastos del Mes" = the detail's total
                items.append((label, amount))
        else:
            continue
        break  # reached the detail
    if res.saldo_inicial is None and res.ingresos is None and not items:
        return None
    egresos = _split_egresos(items, res.ingresos)
    res.items = [
        ResumenItem(concepto=c, importe=a, tipo="egreso" if i in egresos else "ingreso")
        for i, (c, a) in enumerate(items)
    ]
    return res


FONDO_RUBRO = "Fondo de obra"
_FONDO_START = re.compile(r"(?i)^\s*fondo\s+de\s+(obra|reserva)\b")
_FONDO_END = re.compile(r"(?i)^\s*(unidades\s+(con\s+deudas?|en\s+mora)|total\s+expensas)")
_ACCOUNT_CODE = re.compile(r"^\d{2,4}\s+(?=\D)")  # "168 MANO DE OBRA ..." (the administrator's account)
_TRAILING_PAREN = re.compile(r"^(?P<concepto>.*?)\s*\((?P<detalle>[^()]*)\)\s*$")


def _split_fondo(
    items: list[tuple[str, float, int]], saldo_inicial: float, saldo_final: float
) -> set[int] | None:
    """Indexes of the fund's outflows. The text layer loses the Ingresos/Egresos column, but
    saldo inicial + ingresos - egresos = saldo final fixes their sum. Among the subsets that
    add up, prefer the one with more account-coded items ("168 MANO DE OBRA ..."; income
    rows are usually free text). None when nothing, or more than one best subset, adds up."""
    from itertools import combinations

    total = sum(a for _, a, _ in items)
    out = round((total - (saldo_final - saldo_inicial)) / 2, 2)
    if len(items) > 16:
        return None
    best: list[tuple[int, set[int]]] = []
    for k in range(len(items) + 1):
        for combo in combinations(range(len(items)), k):
            if abs(sum(items[i][1] for i in combo) - out) <= TOLERANCE:
                coded = sum(1 for i in combo if _ACCOUNT_CODE.match(items[i][0]))
                best.append((coded, set(combo)))
    if not best:
        return None
    top = max(c for c, _ in best)
    winners = [s for c, s in best if c == top]
    return winners[0] if len(winners) == 1 else None


def parse_fondo(pages: list[tuple[int, str]]) -> tuple[Fondo | None, list[LiquidacionLine]]:
    """The fund ledger; it may continue on the next page (after the page's letterhead)."""
    fondo: Fondo | None = None
    items: list[tuple[str, float, int]] = []
    done = False
    for page_no, text in pages:
        for raw in text.splitlines():
            if fondo is None:
                if _FONDO_START.match(raw):
                    fondo = Fondo()
                continue
            if _FONDO_END.match(raw) or _DEBT_START.search(raw):
                done = True
                break
            am = _AMOUNT_AT_END.match(raw)
            if not am:
                continue  # column header, letterhead of the next page
            label, amount = am.group("text").strip(), parse_amount(am.group("amount"))
            if _SALDO_INICIAL.match(label):
                fondo.saldo_inicial = amount
            elif _SALDO_FINAL.match(label):
                fondo.saldo_final = amount
                done = True
                break
            else:
                items.append((label, amount, page_no))
        if done:
            break
    if fondo is None:
        return None, []
    egresos = (
        _split_fondo(items, fondo.saldo_inicial, fondo.saldo_final)
        if fondo.saldo_inicial is not None and fondo.saldo_final is not None
        else None
    )
    egresos = egresos or set()  # unresolved: validate.check_fondo reports it
    fondo.items = [
        ResumenItem(concepto=c, importe=a, tipo="egreso" if i in egresos else "ingreso")
        for i, (c, a, _) in enumerate(items)
    ]
    lines = []
    for i, (label, amount, page_no) in enumerate(items):
        if i not in egresos:
            continue
        text = _ACCOUNT_CODE.sub("", label).strip()
        pm = _TRAILING_PAREN.match(text)
        concepto, detalle = (
            (pm.group("concepto"), pm.group("detalle").strip())
            if pm and pm.group("concepto")
            else (text, None)
        )
        cuit = _CUIT.search(label)
        lines.append(
            LiquidacionLine(
                rubro=FONDO_RUBRO, concepto=concepto, detalle=detalle or None, cuit=cuit.group(0) if cuit else None,
                importe=amount, page_no=page_no, confidence=0.8, fondo=True,
            )
        )  # fmt: skip
    return fondo, lines


def parse(period: str, pages: list[tuple[int, str]]) -> Liquidacion:
    lines: list[LiquidacionLine] = []
    rubro_totals: list[RubroTotal] = []
    total: float | None = None
    rubro: str | None = None
    has_detail_marker = any(_DETAIL_START.search(ln) for _, t in pages for ln in t.splitlines())
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
    fondo, fondo_lines = parse_fondo(pages)
    return Liquidacion(
        period=period,
        total=total,
        rubro_totals=rubro_totals,
        lines=lines + fondo_lines,
        resumen=parse_resumen(pages),
        fondo=fondo,
    )
