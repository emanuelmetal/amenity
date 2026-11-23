"""Year-close check of one ejercicio (September–August): `alas3 ejercicio`.

The rendición de cuentas is yearly (CCyC art. 2067 e): a month whose receipts arrive late is
not wrong by itself, but at the close every gasto of the ejercicio must be backed and every
receipt used at most once. This puts together:

1. the administrator's balance (balance.py): its own arithmetic, continuity with the previous
   ejercicio, and that its expenses are exactly the liquidaciones of its months;
2. the evidence (review.queue): gastos still without receipt or payment, receipts backing
   more than their amount, receipts nobody used, receipts dated in another ejercicio, and
   rejections marked "comprobante duplicado".

Read-only: prints a report, changes nothing. Findings worth raising go to observations.json.
"""

from __future__ import annotations

from collections import defaultdict

from .balance import arithmetic, continuity, load_balances, reconcile
from .config import EJERCICIO_START_MONTH, ejercicio

CENT = 0.01


def _m(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


def _months(desde: str) -> list[str]:
    y, m = map(int, desde.split("-"))
    out = []
    for _ in range(12):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _liquidaciones() -> dict:
    from .extract import load_extract
    from .ingest import load_manifests
    from .schemas import Liquidacion

    out = {}
    for m in load_manifests():
        if m.kind == "liquidacion":
            e = load_extract(m)
            if isinstance(e, Liquidacion):
                out[e.period] = e
    return out


def balance_section(desde: str) -> list[str]:
    balances = load_balances()
    cur = next((b for b in balances if b.desde == desde or ejercicio(b.hasta) == desde), None)
    out = ["== Balance de la administración =="]
    if cur is None:
        return [*out, f"No hay balance del ejercicio que empieza en {desde} en data/inbox/balances/."]
    out.append(f"{cur.source}: {cur.desde} a {cur.hasta}, gastos {_m(cur.total_gastos)}, "
               f"saldo final {_m(cur.saldo_final)}, {cur.fondo.nombre or 'sin fondo'} {_m(cur.fondo.saldo_final)}")  # fmt: skip
    problems = arithmetic(cur)
    out.append("Aritmética: " + ("cierra." if not problems else ""))
    out += [f"  • {p}" for p in problems]
    prev = [b for b in balances if b.hasta < cur.desde]
    if prev:
        cont = continuity(prev[-1], cur)
        out.append(f"Continuidad con {prev[-1].desde} a {prev[-1].hasta}: " + ("cierra." if not cont else ""))
        out += [f"  • {p}" for p in cont]
        prev_problems = arithmetic(prev[-1])
        if prev_problems:
            out.append(f"Balance anterior ({prev[-1].source}):")
            out += [f"  • {p}" for p in prev_problems]
    else:
        out.append("Continuidad: no hay balance anterior para comparar.")
    rec, missing = reconcile(cur, _liquidaciones())
    if missing and not rec:
        out.append(f"Conciliación con las liquidaciones: faltan {', '.join(missing)}.")
    else:
        out.append("Conciliación con las liquidaciones (por concepto y fondo): " + ("coincide." if not rec else ""))
        out += [f"  • {p}" for p in rec]
    return out


def evidence_section(desde: str) -> list[str]:
    from .review import queue

    months = set(_months(desde))
    q = queue()
    out = ["", "== Respaldo de los gastos del ejercicio =="]
    lines = [ln for ln in q["all_lines"] if ln["period"] in months]
    open_lines = [ln for ln in lines if not ln["settled"]]
    by_month: dict[str, list] = defaultdict(list)
    for ln in open_lines:
        by_month[ln["period"]].append(ln)
    out.append(f"{len(lines)} gastos, {len(lines) - len(open_lines)} respaldados (comprobante y pago cuando corresponde), "
               f"{len(open_lines)} abiertos.")  # fmt: skip
    for p in sorted(by_month):
        ls = by_month[p]
        nr = sum(1 for ln in ls if not ln["receipt"]["settled"] and ln["receipt"]["needed"])
        npay = sum(1 for ln in ls if not ln["payment"]["settled"] and ln["payment"]["needed"])
        pend = sum(1 for ln in ls if ln["receipt"]["pending"] or ln["payment"]["pending"])
        out.append(f"  {p}: {len(ls)} abiertos ({nr} sin comprobante completo, {npay} sin pago completo, "
                   f"{pend} con propuesta para revisar)")  # fmt: skip

    receipts = [t for t in q["receipts"] if (t["period"] or t["bundle_period"]) and
                (t["bundle_period"] in months or t["period"] in months)]  # fmt: skip
    line_amount = {ln["id"]: ln["importe"] for ln in q["all_lines"]}
    over = []
    for t in receipts:
        live = [x for x in t["linked_to"] if x["status"] != "rejected"]
        if len(live) > 1:
            used = sum(line_amount.get(x["line_id"], 0.0) for x in live)
            if used > (t["total"] or 0) + CENT:
                over.append((t, used, live))
    out.append(f"Comprobantes que respaldan más que su importe: {len(over) or 'ninguno'}")
    for t, used, live in over:
        out.append(f"  • {t['proveedor']} {_m(t['total'])} respalda {_m(used)} en "
                   + "; ".join(f"{x['period']} {x['concepto']}" for x in live))
    dup = [r for r in q["rejections"] if (r.get("note") or {}).get("motivo") == "comprobante duplicado"
           and r["line"]["period"] in months]  # fmt: skip
    out.append(f"Rechazados como comprobante duplicado: {len(dup) or 'ninguno'}")
    for r in dup:
        out.append(f"  • {r['line']['period']} {r['line']['concepto']} ← {r['item'].get('proveedor')} {_m(r['item'].get('total') or 0)}")

    unused = [t for t in receipts if not t["linked"] and t["bundle_period"] in months]
    out.append(f"Comprobantes entregados sin gasto: {len(unused)} por {_m(sum(t['total'] or 0 for t in unused))}")
    per_bundle: dict[str, list] = defaultdict(list)
    for t in unused:
        per_bundle[t["bundle_period"]].append(t)
    for p in sorted(per_bundle):
        ts = per_bundle[p]
        out.append(f"  legajo {p}: {len(ts)} por {_m(sum(t['total'] or 0 for t in ts))}")
    other = [t for t in receipts if t["period"] and t["bundle_period"] in months and ejercicio(t["period"]) != desde]
    out.append(f"Comprobantes fechados en otro ejercicio: {len(other) or 'ninguno'}")
    for t in other:
        to = "; ".join(f"{x['period']} {x['concepto']}" for x in t["linked_to"]) or "sin gasto"
        out.append(f"  • legajo {t['bundle_period']}, fecha {t['fecha'] or t['period']}: {t['proveedor']} {_m(t['total'] or 0)} → {to}")
    return out


def report(desde: str | None = None) -> str:
    """`desde`: first month of the ejercicio ("2025-09"); default: the latest balance's."""
    if desde is None:
        balances = load_balances()
        desde = ejercicio(balances[-1].hasta) if balances else None
    if desde is None or int(desde[5:]) != EJERCICIO_START_MONTH:
        raise SystemExit(f"--desde must be the first month of an ejercicio (YYYY-{EJERCICIO_START_MONTH:02d})")
    months = _months(desde)
    head = [f"Ejercicio {months[0]} a {months[-1]}", ""]
    return "\n".join(head + balance_section(desde) + evidence_section(desde)) + "\n"
