"""Bank account statements ("Resumen de cuenta corriente") inside receipts PDFs.

The administrator attaches the month's bank statement to the receipts bundle. Its
debits prove that expense lines were paid (a transfer to the vendor, the EPEC
direct debit) and its commissions and taxes are the "gastos bancarios" line, which
has no other receipt.

Privacy (fail-closed):
- Credit rows are owners' expensas payments (who paid, so also who did not). ingest.py
  blacks them out on the published page (image, PDF and text) using `private_lines`, and
  they are never stored one by one: only their total.
- The full page text is kept privately in raw/pNNN.bank.txt (data/, never published) so
  the balance can still be checked. Every description that leaves this module goes
  through redact_text.
- Transfers of salaries and refunds name a person: blacked out on the page too
  (`private_lines`) and published as "Pago de haberes" / "Reintegro o devolución".
  One the bank's text does not name as such is listed in the transcription (`bank_private`).
- A statement is used only when opening balance + every movement equals the closing
  balance and every daily "Saldo al" checkpoint; otherwise its pages are reported as
  still to transcribe and nothing of it is used.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from .redact import redact_text
from .schemas import BankItem, BankMovement, BankPrivateRow, BankStatement, DocumentManifest

MARKER = "RESUMEN DE CUENTA CORRIENTE"
CENT = 0.005
# Concept codes of commissions, VAT and the tax on bank debits: grouped as "gastos bancarios".
CHARGE_CODES = {"127", "130", "148", "169", "170", "193", "194", "214", "222", "276"}
_CHARGE_TEXT = re.compile(r"^(COM[.\s]|I\.V\.A|IMPUESTO LEY)")
# Every minus sign variant seen in these PDFs (soft hyphen, hyphen, en dash, minus).
_MINUS = "\u00ad\u2013\u2212-"  # soft hyphen, en dash, minus sign, hyphen (last: literal in [ ])
_AMOUNT = rf"[{_MINUS}]?\d{{1,3}}(?:\.\d{{3}})*,\d{{2}}"
_DATE = r"\d{2}/\d{2}/\d{4}"
# A movement row, whatever the spacing between columns (PDF text may collapse it):
# date, optional bank voucher number, concept code ("190", "F40"), description, amount.
_ROW = re.compile(
    rf"^(?P<fecha>{_DATE})\s+(?:(?P<comprobante>\d+)\s+)?(?P<codigo>[A-Z]?\d{{2,3}})\s+"
    rf"(?P<desc>\S.*?)\s+(?P<importe>{_AMOUNT})\s*$"
)
# "SALDO AL INICIO" or "Saldo Al Inicio" (the bank changed it in 2025).
_OPENING_ROW = re.compile(rf"^(?P<fecha>{_DATE})\s+SALDO AL INICIO\s+(?P<importe>{_AMOUNT})\s*$", re.I)
# Any line that starts with a date and ends with an amount: used to fail closed (see row_kinds).
_ANY_ROW = re.compile(rf"^{_DATE}\s.*?(?P<importe>{_AMOUNT})\s*$")
_SALDO_AL = re.compile(rf"^Saldo al (?P<fecha>{_DATE})\s+(?P<importe>{_AMOUNT})\s*$")
_HASTA = re.compile(rf"Per[ií]odo Hasta\s*:\s*(?P<fecha>{_DATE})\s+Saldo\s*:\s*(?P<importe>{_AMOUNT})")
_DESDE = re.compile(rf"Per[ií]odo Desde\s*:\s*(?P<fecha>{_DATE})")
_CUENTA = re.compile(r"Cuenta\s*:\s*(\S+)")
_BANCO = re.compile(r"^(Banco [^:]+?)\s+Cuit", re.M)
_OPENING = re.compile(r"\bSALDO AL INICIO\b", re.I)
# Debits that name a person: published without the name.
_SALARY = re.compile(r"\bHABER(ES)?\b|\bSUELDO|\bSAC\b|AGUINALDO", re.I)
_REFUND = re.compile(r"DEVOLUC|REINTEGR|REEMBOLS", re.I)

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


def _is_continuation(line: str) -> bool:
    """A wrapped description ("disponible", "ALAS I", "MASUET JALIL -"): short, no digits,
    no colon. Footer text ("Fecha de Impresión: 26/01/2026") and legal blurbs are not."""
    return 0 < len(line) <= 40 and not re.search(r"[\d:]", line)


def row_kinds(lines: list[str]) -> list[str | None]:
    """What each line of a statement page is: 'credit', 'debit', 'opening', 'saldo',
    'credit+' / 'debit+' (continuation of the row above) or None (header, footer)."""
    out: list[str | None] = []
    last: str | None = None
    for raw_line in lines:
        line = raw_line.strip()
        kind: str | None = None
        if _SALDO_AL.match(line):
            kind = "saldo"
        elif _OPENING_ROW.match(line):
            kind = "opening"
        elif m := _ROW.match(line) or _ANY_ROW.match(line):
            # A dated line we cannot split into columns still counts: a credit must be
            # blacked out even if the parser cannot read it (parse() then rejects it).
            kind = "credit" if money(m["importe"]) > 0 else "debit"
        elif last in ("credit", "debit") and _is_continuation(line):
            kind = last + "+"
        out.append(kind)
        if kind in ("credit", "debit"):
            last = kind
        elif kind not in ("credit+", "debit+"):
            last = None
    return out


def credit_lines(lines: list[str]) -> set[int]:
    """Indexes of the lines that show an owner's payment (to black out on the page)."""
    return {i for i, k in enumerate(row_kinds(lines)) if k in ("credit", "credit+")}


PRIVATE_DESC = {"reintegro": "Reintegro o devolución", "haberes": "Pago de haberes"}


def _private_row(line: str, rows: Iterable[BankPrivateRow]) -> BankPrivateRow | None:
    """The reviewed entry (transcription `bank_private`) for this movement row, if any."""
    m = _ROW.match(line.strip())
    if not m:
        return None
    return next(
        (r for r in rows if m["comprobante"] == r.comprobante and abs(money(m["importe"]) + r.importe) < CENT), None
    )


def check_private_rows(lines: list[str], rows: Iterable[BankPrivateRow]) -> None:
    """Every `bank_private` row of a page must be found on it: a typo would leave the name published."""
    for r in rows:
        n = sum(_private_row(line, [r]) is not None for line in lines)
        if n != 1:
            raise StatementError(f"bank_private: {n} rows for voucher {r.comprobante} on page {r.page}")


def private_lines(lines: list[str], rows: Iterable[BankPrivateRow] = ()) -> set[int]:
    """Lines to black out on a published statement page: owners' payments, and salary or
    refund transfers (they name a person), each with its wrapped lines."""
    out: set[int] = set()
    hide = False
    for i, (line, kind) in enumerate(zip(lines, row_kinds(lines), strict=True)):
        if kind == "credit":
            hide = True
        elif kind == "debit":
            hide = bool(_SALARY.search(line) or _REFUND.search(line) or _private_row(line, rows))
        elif kind not in ("credit+", "debit+"):
            hide = False
        if hide:
            out.add(i)
    return out


def _clean_desc(s: str) -> str:
    s = re.sub(rf"[{_MINUS}]", "-", s)
    s = re.sub(r"\s*-\s*Dato no disponible\s*", " ", s)
    s = re.sub(r"\s*-\s*$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _is_charge(codigo: str | None, desc: str) -> bool:
    return codigo in CHARGE_CODES or bool(_CHARGE_TEXT.match(desc))


def _public_desc(desc: str) -> str:
    if _SALARY.search(desc):
        return "Pago de haberes"
    if _REFUND.search(desc):
        return "Reintegro o devolución"
    return redact_text(desc) or ""


def parse(
    pages: list[tuple[int, str]], closing: float | None = None, private: Iterable[BankPrivateRow] = ()
) -> BankStatement:
    """pages: [(page_no, full private text)] of ONE statement, in order.

    `closing`: a reviewed correction of a misprinted closing balance (transcription
    `bank_closing`). Used only when it equals opening + movements and the statement has
    "Saldo al" checkpoints, all of them matching: the header alone is what was wrong."""
    if not pages:
        raise StatementError("no pages")
    head = "\n".join(t for _, t in pages)
    desde_m, hasta_m = _DESDE.search(head), _HASTA.search(head)
    if not desde_m or not hasta_m:
        raise StatementError("period or closing balance not found")
    banco_m, cuenta_m = _BANCO.search(head), _CUENTA.search(head)

    saldo_inicial: float | None = None
    raw: list[dict] = []  # movement rows, in order
    checkpoints: list[tuple[int, float]] = []  # (number of rows before it, balance)
    for page_no, text in pages:
        lines = text.split("\n")
        page_private = [r for r in private if r.page == page_no]
        check_private_rows(lines, page_private)
        last: dict | None = None
        for line, kind in zip(lines, row_kinds(lines), strict=True):
            line = line.strip()
            if kind == "saldo":
                checkpoints.append((len(raw), money(_SALDO_AL.match(line)["importe"])))  # type: ignore[index]
            elif kind == "opening":
                if saldo_inicial is not None or raw:
                    raise StatementError(f"page {page_no}: a second opening balance (two statements merged?)")
                saldo_inicial = money(_OPENING_ROW.match(line)["importe"])  # type: ignore[index]
            elif kind in ("credit", "debit"):
                m = _ROW.match(line)
                if not m:
                    raise StatementError(f"page {page_no}: unreadable movement row")
                last = {"fecha": iso(m["fecha"]), "comprobante": m["comprobante"], "codigo": m["codigo"],
                        "desc": m["desc"], "importe": money(m["importe"]), "page_no": page_no,
                        "private": _private_row(line, page_private)}  # fmt: skip
                raw.append(last)
                continue
            elif kind in ("credit+", "debit+") and last is not None:
                last["desc"] += " " + line  # wrapped description ("disponible", "ALAS I")
                continue
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
        if closing is None or abs(closing - running) > CENT or not checkpoints:
            raise StatementError(f"opening + movements = {running:.2f}, closing balance says {saldo_final:.2f}")
        saldo_final = closing

    hasta = iso(hasta_m["fecha"])
    movements: list[BankMovement] = []
    charges: dict[str, list] = defaultdict(lambda: [0.0, 0])
    charge_pages: set[int] = set()
    for r in raw:
        if r["importe"] >= 0:
            continue
        desc = _clean_desc(r["desc"])
        if _is_charge(r["codigo"], desc):
            key = redact_text(re.sub(r"^COM\.\s*", "COM. ", desc)) or ""
            charges[key][0] += -r["importe"]
            charges[key][1] += 1
            charge_pages.add(r["page_no"])
            continue
        movements.append(BankMovement(fecha=r["fecha"], comprobante=r["comprobante"], codigo=r["codigo"],
                                      descripcion=PRIVATE_DESC[r["private"].tipo] if r["private"] else _public_desc(desc), importe=round(-r["importe"], 2), page_nos=[r["page_no"]]))  # fmt: skip
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


def private_text_path(m: DocumentManifest, page_no: int):
    from .ingest import doc_dir

    return doc_dir(m) / "raw" / f"p{page_no:03d}.bank.txt"


def statements(
    m: DocumentManifest, closings: dict[int, float] | None = None, private: Iterable[BankPrivateRow] = ()
) -> tuple[list[BankStatement], list[int]]:
    """Statements in a document, and the statement pages that could not be verified.

    Consecutive statement pages form one statement; a new account number or a new
    opening balance starts another. Restricted pages are never read. `closings`: first page
    of a statement -> its corrected closing balance (see parse). The text comes
    from the private copy ingest keeps (credit rows are blacked out on the public page).
    """
    groups: list[list[tuple[int, str]]] = []
    failed: list[int] = []
    prev_no, prev_cuenta = None, None
    for p in m.pages:
        if p.restricted or not is_statement_page(p.text):
            prev_no = None
            continue
        path = private_text_path(m, p.page_no)
        if not path.exists():
            print(f"  ! {m.source_name} p.{p.page_no}: bank statement page needs `make ingest ARGS=--force`")
            failed.append(p.page_no)
            prev_no = None
            continue
        text = path.read_text()
        c = _CUENTA.search(text)
        cuenta = c.group(1) if c else prev_cuenta
        starts = bool(_OPENING.search(text))
        if prev_no is not None and p.page_no == prev_no + 1 and cuenta == prev_cuenta and not starts:
            groups[-1].append((p.page_no, text))
        else:
            groups.append([(p.page_no, text)])
        prev_no, prev_cuenta = p.page_no, cuenta
    read = {n for g in groups for n, _ in g}
    if stray := [r.page for r in private if r.page not in read]:
        raise ValueError(f"{m.source_name}: bank_private on pages that are not a readable statement: {stray}")
    out: list[BankStatement] = []
    for g in groups:
        try:
            out.append(parse(g, (closings or {}).get(g[0][0]), private))
        except StatementError as e:
            print(f"  ! {m.source_name} pages {g[0][0]}-{g[-1][0]}: bank statement not verified: {e}")
            failed += [n for n, _ in g]
    return out, sorted(failed)
