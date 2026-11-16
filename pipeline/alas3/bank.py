"""Bank account statements ("Resumen de cuenta corriente") inside receipts PDFs.

The administrator attaches the month's bank statement to the receipts bundle. Its
debits prove that expense lines were paid (a transfer to the vendor, the EPEC
direct debit) and its commissions and taxes are the "gastos bancarios" line, which
has no other receipt.

Parsed from the page text already stored in the manifest (digital PDF text, CUIL/CBU
masked by redact.py). Fail-closed: the statement is used only when its opening
balance plus every movement equals the closing balance and every daily "Saldo al"
checkpoint; otherwise its pages are reported as still to transcribe.

Only debits are kept one by one. Credits are owners' expensas payments and are
kept as one total.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .schemas import BankItem, BankMovement, BankStatement, DocumentManifest

MARKER = "RESUMEN DE CUENTA CORRIENTE"
CENT = 0.005
# Concept codes of commissions, VAT and the tax on bank debits: grouped as "gastos bancarios".
CHARGE_CODES = {"127", "130", "148", "169", "170", "193", "194", "214", "222", "276"}
_CHARGE_TEXT = re.compile(r"^(COM[.\s]|I\.V\.A|IMPUESTO LEY)")
# Every minus sign variant seen in these PDFs (soft hyphen, hyphen, en dash, minus).
_MINUS = "­-–−"
_AMOUNT = rf"[{_MINUS}]?\s*\d{{1,3}}(?:\.\d{{3}})*,\d{{2}}"
_DATE = r"\d{2}/\d{2}/\d{4}"
_ROW = re.compile(rf"^(?P<fecha>{_DATE})\s{{2,}}(?P<body>.*?)\s{{2,}}(?P<importe>{_AMOUNT})\s*$")
_SALDO_AL = re.compile(rf"^Saldo al (?P<fecha>{_DATE})\s+(?P<importe>{_AMOUNT})\s*$")
_HASTA = re.compile(rf"Per[ií]odo Hasta\s*:\s*(?P<fecha>{_DATE})\s+Saldo\s*:\s*(?P<importe>{_AMOUNT})")
_DESDE = re.compile(rf"Per[ií]odo Desde\s*:\s*(?P<fecha>{_DATE})")
_CUENTA = re.compile(r"Cuenta\s*:\s*(\S+)")
_BANCO = re.compile(r"^(Banco [^:]+?)\s+Cuit", re.M)
_NOT_CONTINUATION = re.compile(rf"^({_DATE}|Saldo al|Fecha |Hora |DE INTERES)")

MONTHS = "ene feb mar abr may jun jul ago sep oct nov dic".split()


class StatementError(ValueError):
    pass


def money(s: str) -> float:
    s = s.replace(" ", "")
    neg = s[0] in _MINUS
    v = float(s.lstrip(_MINUS).replace(".", "").replace(",", "."))
    return -v if neg else v


def iso(d: str) -> str:
    dd, mm, yy = d.split("/")
    return f"{yy}-{mm}-{dd}"


def is_statement_page(text: str) -> bool:
    return MARKER in text


def _clean_desc(s: str) -> str:
    s = re.sub(rf"[{_MINUS}]", "-", s)
    s = re.sub(r"\s*-\s*Dato no disponible\s*", " ", s)
    s = re.sub(r"\s*-\s*$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _is_charge(codigo: str | None, desc: str) -> bool:
    return codigo in CHARGE_CODES or bool(_CHARGE_TEXT.match(desc))


def parse(pages: list[tuple[int, str]]) -> BankStatement:
    """pages: [(page_no, redacted text)] of ONE statement, in order."""
    if not pages:
        raise StatementError("no pages")
    head = pages[0][1]
    desde_m, hasta_m = _DESDE.search(head), _HASTA.search(head)
    if not desde_m or not hasta_m:
        raise StatementError("period or closing balance not found")
    banco_m, cuenta_m = _BANCO.search(head), _CUENTA.search(head)

    saldo_inicial: float | None = None
    raw: list[dict] = []  # movement rows, in order
    checkpoints: list[tuple[int, float]] = []  # (number of rows before it, balance)
    for page_no, text in pages:
        last: dict | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if m := _SALDO_AL.match(line):
                checkpoints.append((len(raw), money(m["importe"])))
                last = None
                continue
            if m := _ROW.match(line):
                parts = re.split(r"\s{2,}", m["body"].strip())
                if parts == ["SALDO AL INICIO"]:
                    saldo_inicial = money(m["importe"])
                    last = None
                    continue
                if len(parts) >= 3:
                    comprobante, codigo, desc = parts[0], parts[1], "  ".join(parts[2:])
                elif len(parts) == 2:
                    comprobante, codigo, desc = None, parts[0], parts[1]
                else:
                    raise StatementError(f"page {page_no}: unreadable row {line!r}")
                last = {"fecha": iso(m["fecha"]), "comprobante": comprobante, "codigo": codigo,
                        "desc": desc, "importe": money(m["importe"]), "page_no": page_no}  # fmt: skip
                raw.append(last)
                continue
            if last is not None and not _NOT_CONTINUATION.match(line):
                last["desc"] += " " + line  # wrapped description ("disponible", "ALAS I")
            else:
                last = None

    if saldo_inicial is None:
        raise StatementError("opening balance not found")
    saldo_final = money(hasta_m["importe"])
    running = saldo_inicial
    for i, r in enumerate(raw):
        for n, bal in checkpoints:
            if n == i and abs(running - bal) > CENT:
                raise StatementError(f"balance {running:.2f} != 'Saldo al' {bal:.2f} before row {i}")
        running = round(running + r["importe"], 2)
    for n, bal in checkpoints:
        if n == len(raw) and abs(running - bal) > CENT:
            raise StatementError(f"balance {running:.2f} != 'Saldo al' {bal:.2f} at the end")
    if abs(running - saldo_final) > CENT:
        raise StatementError(f"opening + movements = {running:.2f}, closing balance says {saldo_final:.2f}")

    hasta = iso(hasta_m["fecha"])
    movements: list[BankMovement] = []
    charges: dict[str, list] = defaultdict(lambda: [0.0, 0])
    charge_pages: set[int] = set()
    for r in raw:
        if r["importe"] >= 0:
            continue
        desc = _clean_desc(r["desc"])
        if _is_charge(r["codigo"], desc):
            key = re.sub(r"^COM\.\s*", "COM. ", desc)
            charges[key][0] += -r["importe"]
            charges[key][1] += 1
            charge_pages.add(r["page_no"])
            continue
        movements.append(BankMovement(fecha=r["fecha"], comprobante=r["comprobante"], codigo=r["codigo"],
                                      descripcion=desc, importe=round(-r["importe"], 2), page_nos=[r["page_no"]]))  # fmt: skip
    if charges:
        items = [BankItem(descripcion=k, importe=round(v[0], 2), cantidad=v[1])
                 for k, v in sorted(charges.items(), key=lambda kv: -kv[1][0])]  # fmt: skip
        y, mth = int(hasta[:4]), int(hasta[5:7])
        movements.append(BankMovement(
            fecha=hasta, descripcion=f"Gastos bancarios {MONTHS[mth - 1]} {y} (comisiones e impuestos)",
            importe=round(sum(i.importe for i in items), 2), kind="gastos",
            page_nos=sorted(charge_pages), items=items))  # fmt: skip

    return BankStatement(
        banco=banco_m.group(1).strip() if banco_m else "Banco",
        cuenta=cuenta_m.group(1) if cuenta_m else None,
        desde=iso(desde_m["fecha"]),
        hasta=hasta,
        saldo_inicial=saldo_inicial,
        saldo_final=saldo_final,
        creditos=round(sum(r["importe"] for r in raw if r["importe"] > 0), 2),
        debitos=round(-sum(r["importe"] for r in raw if r["importe"] < 0), 2),
        page_nos=[p for p, _ in pages],
        movements=movements,
    )


def statements(m: DocumentManifest) -> tuple[list[BankStatement], list[int]]:
    """Statements in a document, and the statement pages that could not be verified.

    Consecutive statement pages with the same period form one statement. Restricted
    pages are never read.
    """
    groups: list[list[tuple[int, str]]] = []
    prev_no, prev_key = None, None
    for p in m.pages:
        if p.restricted or not is_statement_page(p.text):
            prev_no = None
            continue
        d, h = _DESDE.search(p.text), _HASTA.search(p.text)
        key = (d and d["fecha"], h and h["fecha"])
        if prev_no is not None and p.page_no == prev_no + 1 and key == prev_key:
            groups[-1].append((p.page_no, p.text))
        else:
            groups.append([(p.page_no, p.text)])
        prev_no, prev_key = p.page_no, key
    out: list[BankStatement] = []
    failed: list[int] = []
    for g in groups:
        try:
            out.append(parse(g))
        except StatementError as e:
            print(f"  ! {m.source_name} pages {g[0][0]}-{g[-1][0]}: bank statement not verified: {e}")
            failed += [n for n, _ in g]
    return out, failed
