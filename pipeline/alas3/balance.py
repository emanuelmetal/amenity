"""The administrator's yearly "Balance de Gastos y Cobranzas" (data/inbox/balances/*.pdf).

It is the ejercicio's summary (CCyC art. 2067 e): income and expenses of the operating account,
expenses by rubro and concepto, the reserve / works fund and the closing position. Parsed from
the PDF's text with word positions (amounts are right-aligned in their column), used only for
the year-close check (`alas3 ejercicio`): never published.

Checks: its own arithmetic, continuity with the previous balance, and that its expenses are
exactly the liquidaciones of its months (by concepto, and the fund's).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import INBOX

AMOUNT = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}$")
CENT = 0.01


def money(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def norm(s: str) -> str:
    """Concepto key: upper case, no accents, single spaces ("Impermeabilización" = "IMPERMEABILIZACION")."""
    s = unicodedata.normalize("NFD", s.upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Fund:
    nombre: str = ""
    saldo_inicial: float = 0.0
    ingresos: list[tuple[str, float]] = field(default_factory=list)
    egresos: list[tuple[str, float]] = field(default_factory=list)
    saldo_final: float = 0.0


@dataclass
class Rubro:
    nombre: str
    total: float
    items: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Balance:
    source: str
    desde: str = ""  # YYYY-MM
    hasta: str = ""
    saldo_inicial: float = 0.0
    ingresos: list[tuple[str, float]] = field(default_factory=list)
    egresos: list[tuple[str, float]] = field(default_factory=list)  # besides "Total de Gastos"
    total_gastos: float = 0.0
    saldo_final: float = 0.0
    rubros: list[Rubro] = field(default_factory=list)
    total_detalle: float = 0.0
    fondo: Fund = field(default_factory=Fund)
    cierre: dict[str, float] = field(default_factory=dict)

    def months(self) -> list[str]:
        y, m = map(int, self.desde.split("-"))
        out = []
        while f"{y}-{m:02d}" <= self.hasta:
            out.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out


def _lines(path: Path) -> list[tuple[str, list[tuple[float, float]]]]:
    """Each text line as (label, [(amount, right edge x)]), in reading order."""
    import pymupdf

    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            rows: dict[int, list] = defaultdict(list)
            for w in page.get_text("words"):
                rows[round(w[1] / 3)].append(w)
            for y in sorted(rows):
                # "$21.790.411,25": the currency sign can be glued to the amount.
                ws = [(*w[:4], w[4].lstrip("$") or "$", *w[5:]) for w in sorted(rows[y], key=lambda w: w[0])]
                label = " ".join(w[4] for w in ws if not AMOUNT.match(w[4]) and w[4] != "$")
                amounts = [(money(w[4]), w[2]) for w in ws if AMOUNT.match(w[4])]
                out.append((label.strip(), amounts))
    return out


def _col(x: float, cols: dict[str, float]) -> str:
    return min(cols, key=lambda k: abs(cols[k] - x))


def parse_balance(path: Path) -> Balance:
    b = Balance(source=path.name)
    section = None
    cols: dict[str, float] = {}
    rubro: Rubro | None = None
    last: list | None = None  # the row a label-only continuation line belongs to
    for label, amounts in _lines(path):
        up = norm(label)
        if m := re.search(r"PERIODOS (\d{2})/(\d{4}) Y EL (\d{2})/(\d{4})", up):
            if not b.desde:
                b.desde, b.hasta = f"{m[2]}-{m[1]}", f"{m[4]}-{m[3]}"
            section = "detalle" if up.startswith("DETALLE") else "resumen"
            continue
        if up.startswith("PAGINA") or up.startswith("ESTUDIO") or not (label or amounts):
            continue
        if up.startswith("FONDO DE") and not amounts:
            # "FONDO DE RESERVA  INGRESOS  EGRESOS" is one line: the label is the fund's name.
            name = re.sub(r"\s*INGRESOS\s+EGRESOS\s*$", "", label)
            section, b.fondo.nombre, cols = "fondo", name, {"ingreso": 495.0, "egreso": 585.0}
            continue
        if section in (None, "fin"):
            if section == "fin" and amounts:
                b.cierre[label] = amounts[0][0]
            continue
        if not amounts:
            if section == "resumen" and "Ingreso" in label.split():
                cols = {"ingreso": 470.0, "egreso": 580.0}
            elif section == "detalle" and "Tot.Rubro" in label:
                cols = {"item": 360.0, "rubro": 540.0, "pct": 585.0}
            elif section == "fondo" and "INGRESOS" in up:
                cols = {"ingreso": 495.0, "egreso": 585.0}
            elif last is not None and section != "resumen":
                last[0] = f"{last[0]} {label}"  # "INTERVENCION GASISTA" + "MATRICULADO"
            continue
        if section == "resumen":
            value, x = amounts[0]
            if up.startswith(("SALDO INICIAL", "DEFICIT INICIAL")):
                b.saldo_inicial = value
            elif up.startswith("TOTAL DE GASTOS"):
                b.total_gastos = value
            elif up.startswith("SALDO FINAL"):
                b.saldo_final = value
            else:
                (b.ingresos if _col(x, cols or {"ingreso": 470.0, "egreso": 580.0}) == "ingreso" else b.egresos).append(
                    (label, value)
                )
        elif section == "detalle":
            if up.startswith("TOTAL DE GASTOS DEL PERIODO"):
                b.total_detalle = max(v for v, _ in amounts)
                section, last = "between", None
                continue
            kept = [(v, x) for v, x in amounts if _col(x, cols) != "pct"]
            value, x = kept[0]
            if _col(x, cols) == "rubro":
                rubro = Rubro(label, value)
                b.rubros.append(rubro)
                last = None
            elif rubro is not None:
                row = [label, value]
                rubro.items.append(row)  # type: ignore[arg-type]
                last = row
        elif section == "fondo":
            value, x = amounts[0]
            if up.startswith("SALDO INICIAL"):
                b.fondo.saldo_inicial = value
            elif up.startswith("SALDO FINAL"):
                b.fondo.saldo_final = value
                section = "fin"
            else:
                side = b.fondo.ingresos if _col(x, cols) == "ingreso" else b.fondo.egresos
                side.append((label, value))
    for r in b.rubros:
        r.items = [(str(n), float(v)) for n, v in r.items]
    return b


def load_balances(folder: Path | None = None) -> list[Balance]:
    """Every balance in data/inbox/balances/, oldest period first."""
    folder = folder or INBOX / "balances"
    return sorted((parse_balance(p) for p in sorted(folder.glob("*.pdf"))), key=lambda b: (b.hasta, b.desde))


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= CENT


def _m(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


def arithmetic(b: Balance) -> list[str]:
    """Problems in the balance's own sums (empty = it adds up)."""
    out = []
    ing, egr = sum(v for _, v in b.ingresos), sum(v for _, v in b.egresos)
    expected = round(b.saldo_inicial + ing - egr - b.total_gastos, 2)
    if not _close(expected, b.saldo_final):
        out.append(f"saldo inicial + ingresos − egresos = {_m(expected)}, pero el saldo final dice {_m(b.saldo_final)}")
    rubros = round(sum(r.total for r in b.rubros), 2)
    if not _close(rubros, b.total_gastos):
        out.append(f"los rubros suman {_m(rubros)} y el total de gastos es {_m(b.total_gastos)}")
    for r in b.rubros:
        s = round(sum(v for _, v in r.items), 2)
        if not _close(s, r.total):
            out.append(f"rubro {r.nombre}: sus conceptos suman {_m(s)} y el total del rubro es {_m(r.total)}")
    f = b.fondo
    if f.nombre:
        fe = round(f.saldo_inicial + sum(v for _, v in f.ingresos) - sum(v for _, v in f.egresos), 2)
        if not _close(fe, f.saldo_final):
            out.append(f"{f.nombre}: saldo inicial + ingresos − egresos = {_m(fe)}, pero el saldo final dice {_m(f.saldo_final)}")
    c = {norm(k): v for k, v in b.cierre.items()}
    disp = next((v for k, v in c.items() if k.startswith("SALDO DISPONIBLE")), None)
    if disp is not None and not _close(disp, b.saldo_final + f.saldo_final):
        out.append(f"saldo disponible {_m(disp)} ≠ saldo final {_m(b.saldo_final)} + fondo {_m(f.saldo_final)}")
    activo = next((v for k, v in c.items() if k.startswith("TOTAL DEL ACTIVO")), None)
    parts = [v for k, v in c.items() if k.startswith(("SALDO DISPONIBLE", "CREDITOS", "BIENES DE USO"))]
    if activo is not None and not _close(activo, sum(parts)):
        out.append(f"el total del activo {_m(activo)} no es la suma de sus partes {_m(sum(parts))}")
    deudas = next((v for k, v in c.items() if k.startswith("DEUDAS")), None)
    result = next((v for k, v in c.items() if k.startswith("INTEGRACION")), None)
    if None not in (activo, deudas, result) and not _close(result, activo - deudas):  # type: ignore[operator]
        out.append(f"el resultado {_m(result)} no es activo − deudas {_m(activo - deudas)}")  # type: ignore[operator]
    if len(b.months()) != 12:
        out.append(f"abarca {len(b.months())} meses ({b.desde} a {b.hasta}), no 12")
    return out


def continuity(prev: Balance, cur: Balance) -> list[str]:
    """What does not carry over from one ejercicio to the next."""
    out = []
    if not _close(prev.saldo_final, cur.saldo_inicial):
        out.append(f"saldo final {prev.hasta} {_m(prev.saldo_final)} ≠ saldo inicial {cur.desde} {_m(cur.saldo_inicial)} "
                   f"(diferencia {_m(cur.saldo_inicial - prev.saldo_final)})")  # fmt: skip
    if prev.fondo.nombre and not _close(prev.fondo.saldo_final, cur.fondo.saldo_inicial):
        out.append(f"{prev.fondo.nombre} final {_m(prev.fondo.saldo_final)} ≠ {cur.fondo.nombre} inicial "
                   f"{_m(cur.fondo.saldo_inicial)} (diferencia {_m(cur.fondo.saldo_inicial - prev.fondo.saldo_final)})")  # fmt: skip
    months = prev.months()
    if cur.desde in months:
        out.append(f"el mes {cur.desde} está en los dos balances")
    return out


def reconcile(b: Balance, liquidaciones: dict) -> tuple[list[str], list[str]]:
    """The balance's expenses against the liquidaciones of its months.

    Returns (problems, months without a liquidación). Lines paid from the fund (`fondo`) are
    compared with the fund's expenses, the rest with the balance's conceptos."""
    have = [p for p in b.months() if p in liquidaciones]
    missing = [p for p in b.months() if p not in liquidaciones]
    if not have:
        return [], missing
    lines: dict[str, float] = defaultdict(float)
    fund = 0.0
    for p in have:
        for ln in liquidaciones[p].lines:
            if ln.fondo:
                fund += ln.importe
            else:
                lines[norm(ln.concepto)] += ln.importe
    out = []
    if missing:
        return [f"faltan las liquidaciones de {', '.join(missing)}: no se puede conciliar"], missing
    bal: dict[str, float] = defaultdict(float)
    for r in b.rubros:
        for name, v in r.items:
            bal[norm(name)] += v
    for k in sorted(set(lines) | set(bal)):
        if not _close(lines.get(k, 0.0), bal.get(k, 0.0)):
            out.append(f"{k}: liquidaciones {_m(lines.get(k, 0.0))}, balance {_m(bal.get(k, 0.0))}")
    total = round(sum(lines.values()), 2)
    if not _close(total, b.total_gastos):
        out.append(f"total de gastos: liquidaciones {_m(total)}, balance {_m(b.total_gastos)}")
    fund_out = round(sum(v for _, v in b.fondo.egresos), 2)
    if b.fondo.nombre and not _close(round(fund, 2), fund_out):
        out.append(f"gastos pagados con el fondo: liquidaciones {_m(fund)}, balance {_m(fund_out)}")
    return out, missing
