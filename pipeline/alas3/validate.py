"""Step 7: sum checks. Σ lines = rubro total, Σ rubros = liquidación total."""

from __future__ import annotations

from collections import defaultdict

from .schemas import Liquidacion

TOLERANCE = 0.01


def check_liquidacion(liq: Liquidacion) -> list[str]:
    problems: list[str] = []
    if not liq.lines:
        return [f"{liq.period}: no lines extracted"]
    by_rubro: dict[str, float] = defaultdict(float)
    for line in liq.lines:
        by_rubro[line.rubro] += line.importe
    for rt in liq.rubro_totals:
        got = by_rubro.get(rt.rubro, 0.0)
        if abs(got - rt.total) > TOLERANCE:
            problems.append(f"{liq.period} {rt.rubro}: lines sum {got:,.2f} != rubro total {rt.total:,.2f}")
    missing = set(by_rubro) - {rt.rubro for rt in liq.rubro_totals}
    if liq.rubro_totals and missing:
        problems.append(f"{liq.period}: rubros without a total line: {sorted(missing)}")
    if liq.total is not None:
        s = sum(by_rubro.values())
        if abs(s - liq.total) > TOLERANCE:
            problems.append(f"{liq.period}: lines sum {s:,.2f} != liquidación total {liq.total:,.2f}")
    else:
        problems.append(f"{liq.period}: no grand total found")
    return problems
