"""Pydantic schemas for everything the pipeline produces (PLAN.md §4–5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DocKind = Literal["liquidacion", "comprobantes", "reglamento", "acta", "otro"]


class PageRecord(BaseModel):
    page_no: int  # 1-based
    text: str = ""  # already redacted
    ocr_engine: Literal["pdf-text", "tesseract", "paddle", "manual", "none"] = "none"
    has_qr: bool = False
    restricted: bool = False
    restricted_reason: str | None = None
    hidden_lines: int = 0  # lines blacked out (e.g. debt list) on a published page
    redacted_strings: int = 0  # personal identifiers blacked out on the page


class DocumentManifest(BaseModel):
    id: int
    kind: DocKind
    period: str | None = None  # 'YYYY-MM'
    title: str
    source_name: str
    sha256: str
    pages: list[PageRecord] = Field(default_factory=list)

    @property
    def work_dir_name(self) -> str:
        return self.sha256[:16]

    def page_id(self, page_no: int) -> int:
        from .config import PAGE_ID_FACTOR

        return self.id * PAGE_ID_FACTOR + page_no


class LiquidacionLine(BaseModel):
    rubro: str
    concepto: str
    importe: float
    detalle: str | None = None
    subcategoria: str | None = None
    proveedor: str | None = None
    cuit: str | None = None
    page_no: int | None = None
    confidence: float = Field(1.0, ge=0, le=1)
    verified: bool = False
    fondo: bool = False  # paid from the Fondo de obra/reserva: not part of the month's total


class RubroTotal(BaseModel):
    rubro: str
    total: float


class ResumenItem(BaseModel):
    concepto: str
    importe: float
    tipo: Literal["ingreso", "egreso"]


class Resumen(BaseModel):
    """The "Resumen de cuenta" block at the top of a liquidación."""

    saldo_inicial: float | None = None
    saldo_final: float | None = None
    ingresos: float | None = None  # "INGRESOS PERÍODO"
    egresos: float | None = None  # "EGRESOS PERÍODO" (expense detail + other outflows)
    items: list[ResumenItem] = Field(default_factory=list)


class Fondo(BaseModel):
    """The "FONDO DE OBRA" / "FONDO DE RESERVA" ledger below the expense detail (the same
    fund under two names). Its outflows are also LiquidacionLine(fondo=True)."""

    saldo_inicial: float | None = None
    saldo_final: float | None = None
    items: list[ResumenItem] = Field(default_factory=list)


class Liquidacion(BaseModel):
    period: str
    total: float | None = None
    rubro_totals: list[RubroTotal] = Field(default_factory=list)
    lines: list[LiquidacionLine]
    resumen: Resumen | None = None
    fondo: Fondo | None = None


class ReglamentoArticle(BaseModel):
    numero: str
    orden: int
    titulo: str | None = None
    texto: str
    page_nos: list[int]
    verified: bool = False


class Reglamento(BaseModel):
    articles: list[ReglamentoArticle]


class TicketItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    descripcion: str
    cantidad: float | None = None
    importe: float | None = None


TicketKind = Literal[
    "factura", "recibo", "presupuesto", "ticket", "servicio", "nota_credito", "nota_debito", "otro"
]


class Ticket(BaseModel):
    """A receipt (comprobante). Fields from an ARCA QR are exact (source='qr')."""

    model_config = ConfigDict(extra="forbid")
    page_nos: list[int] = Field(min_length=1)  # copies and multi-page receipts share one ticket
    kind: TicketKind = "otro"
    fecha: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    proveedor: str | None = None
    cuit: str | None = None
    tipo_cmp: int | None = None
    letra: str | None = Field(None, pattern=r"^[A-Z]$")
    pto_vta: int | None = Field(None, ge=0)
    nro_cmp: int | None = Field(None, ge=0)
    cae: str | None = Field(None, pattern=r"^\d{8,20}$")
    total: float | None = Field(None, allow_inf_nan=False)
    medio_pago: str | None = None
    descripcion: str | None = None
    items: list[TicketItem] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source: Literal["qr", "llm", "manual"] = "llm"
    confidence: float = Field(0.0, ge=0, le=1)
    # Filled by the pipeline, not by transcription:
    privado: bool = False  # read from a restricted payroll page (PrivateReceipt): no page is published
    period: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")
    subcategoria: str | None = None
    tags: list[str] = Field(default_factory=list)
    verified: bool = False

    def key(self) -> tuple | None:
        """Identity of a fiscal voucher (the same invoice in ORIGINAL/DUPLICADO copies)."""
        if self.pto_vta is None or self.nro_cmp is None:
            return None
        return (self.cuit and self.cuit.replace("-", ""), self.tipo_cmp, self.pto_vta, self.nro_cmp)


class Blackout(BaseModel):
    """An area of a page to black out, as fractions of the displayed page (0..1)."""

    model_config = ConfigDict(extra="forbid")
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    motivo: str = "CUIT"

    @model_validator(mode="after")
    def _ordered(self) -> Blackout:
        if not (self.x0 < self.x1 and self.y0 < self.y1):
            raise ValueError("x0 < x1 and y0 < y1 required")
        return self


class IgnoredQR(BaseModel):
    """A QR printed on a receipt that encodes another voucher (a vendor reusing an old
    QR image). Still blacked out on the page; it just does not become a receipt."""

    model_config = ConfigDict(extra="forbid")
    page: int
    pto_vta: int
    nro_cmp: int
    motivo: str = Field(min_length=3)


class Cheque(BaseModel):
    """A cheque the consortium issued, photographed in the receipts bundle: evidence that an
    expense was paid. The bank debit that cleared it ("CHEQUE CAMARA RECIBIDA") carries its
    number as voucher; until it clears, the cheque alone is the payment (payments.py)."""

    model_config = ConfigDict(extra="forbid")
    numero: str = Field(pattern=r"^\d{6,10}$")
    banco: str
    importe: float = Field(gt=0)
    fecha_emision: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_pago: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    page: int
    beneficiario: str | None = None  # "Páguese a", when written

    @property
    def key(self) -> str:
        return self.numero.lstrip("0")


# Concepts that may be read from a restricted payroll page -> what the public site calls the
# document. A fixed list on purpose: nothing else (names, CUIL, the salary breakdown) is ever
# transcribed from those pages.
PRIVATE_CONCEPTS = {
    "sueldo neto": "Recibo de sueldo",
    "sueldo bruto": "Recibo de sueldo",
    "SAC": "Recibo de sueldo",
    "vacaciones": "Recibo de sueldo",
    "cargas sociales (F.931)": "Costo laboral",
    "SUTERyH": "Costo laboral",
    "FATERyH": "Costo laboral",
    "seguro de vida obligatorio": "Costo laboral",
    "SUSS + sindicatos": "Costo laboral",
    "SUSS + sindicatos + seguro": "Costo laboral",
}


PRIVATE_CROP_MAX_AREA = 0.06  # of the page: a box around one amount or period, never more


class PrivateCrop(BaseModel):
    """Where a private receipt's amount or period sits on its payroll page, as fractions of
    the page (0..1). Only the local review renders it (on the fly, never stored or published),
    so the reviewer can check the transcribed total without seeing the rest of the page."""

    model_config = ConfigDict(extra="forbid")
    campo: Literal["importe", "periodo"]
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _small(self) -> PrivateCrop:
        if not (self.x0 < self.x1 and self.y0 < self.y1):
            raise ValueError("x0 < x1 and y0 < y1 required")
        if (self.x1 - self.x0) * (self.y1 - self.y0) > PRIVATE_CROP_MAX_AREA:
            raise ValueError(f"crop larger than {PRIVATE_CROP_MAX_AREA:.0%} of the page: only the amount/period box")
        return self


class PrivateReceipt(BaseModel):
    """A total read from a restricted payroll page (payslip, labour-cost summary). It backs a
    salary or social-charges line like a receipt, but nothing of the page is published: the
    site shows "<document> (documento privado)", no image, and the amounts of the lines it is
    linked to (already public in the liquidación). Never published while unlinked."""

    model_config = ConfigDict(extra="forbid")
    page: int
    concepto: Literal[tuple(PRIVATE_CONCEPTS)]  # type: ignore[valid-type]
    total: float = Field(gt=0, allow_inf_nan=False)
    periodo: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")  # month it pays (default: the bundle's)
    # Boxes the local review crops from the page to check total/period (never published).
    crops: list[PrivateCrop] = Field(default_factory=list)


class BankClosingFix(BaseModel):
    """A bank statement whose header misprints the closing balance: every "Saldo al" matches
    and the next statement opens with opening + movements. Checked by bank.parse."""

    model_config = ConfigDict(extra="forbid")
    page: int  # first page of the statement
    saldo_final: float
    motivo: str = Field(min_length=10)


class TicketTranscription(BaseModel):
    """data/work/extract/<sha16>.tickets.json: hand/Claude transcription of a receipts PDF."""

    model_config = ConfigDict(extra="forbid")
    tickets: list[Ticket] = Field(default_factory=list)
    ignore_qr: list[IgnoredQR] = Field(default_factory=list)
    # Scanned/photographed pages someone has looked at: page -> areas to black out, each
    # [x0, y0, x1, y1] as fractions (0..1) of the page as displayed. [] = nothing to hide.
    # OCR cannot be trusted to find a CUIT on a photo, so unchecked scans are never published.
    checked: dict[int, list[Blackout]] = Field(default_factory=dict)
    # Pages that hold no receipt, with what they are ("extracto bancario", "contrato", ...).
    other_pages: dict[int, str] = Field(default_factory=dict)
    # Cheques photographed in the bundle (their page must be in `checked`: account data and
    # signatures blacked out).
    cheques: list[Cheque] = Field(default_factory=list)
    # Totals from restricted payroll pages (see PrivateReceipt). The page must be restricted.
    private_receipts: list[PrivateReceipt] = Field(default_factory=list)
    # Statements whose printed closing balance is wrong (see BankClosingFix).
    bank_closing: list[BankClosingFix] = Field(default_factory=list)


class BankItem(BaseModel):
    """One concept of a grouped charge ("IMPUESTO LEY 25413" x 41)."""

    descripcion: str
    importe: float  # positive: money that left the account
    cantidad: int = 1


class BankMovement(BaseModel):
    """A debit of the consortium's bank account: evidence that an expense was paid.

    kind 'debito' = one outgoing movement (transfer, direct debit); 'gastos' = every
    commission and tax of the statement grouped into one (the "gastos bancarios" line);
    'cheque' = a cheque that no statement shows cleared yet (payments.py builds it).
    Credits (owners' expensas payments) are never stored one by one.
    """

    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    comprobante: str | None = None
    codigo: str | None = None
    descripcion: str
    importe: float  # positive: money that left the account
    kind: Literal["debito", "gastos", "cheque"] = "debito"
    page_nos: list[int] = Field(min_length=1)
    items: list[BankItem] = Field(default_factory=list)

    @property
    def period(self) -> str:
        return self.fecha[:7]


class BankStatement(BaseModel):
    """A bank account statement ("Resumen de cuenta corriente") found in a receipts PDF."""

    banco: str
    cuenta: str | None = None
    desde: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    hasta: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    saldo_inicial: float
    saldo_final: float
    creditos: float  # total credited (owners' payments), as one number
    debitos: float  # total debited, charges included
    page_nos: list[int]
    movements: list[BankMovement]


class Comprobantes(BaseModel):
    tickets: list[Ticket]
    other_pages: dict[int, str] = Field(default_factory=dict)
    untranscribed: list[int] = Field(default_factory=list)  # pages still to transcribe
    bank: list[BankStatement] = Field(default_factory=list)
    cheques: list[Cheque] = Field(default_factory=list)


class ActaItem(BaseModel):
    tipo: Literal["decision", "tarea", "tema"]
    texto: str
    importe: float | None = None


class Acta(BaseModel):
    fecha: str
    resumen: str | None = None
    items: list[ActaItem] = Field(default_factory=list)


REJECT_REASONS = (
    "tapado por la redacción",  # the blackout hides the amount or the description: fix the blackout
    "importe distinto",
    "otro proveedor",
    "otro mes",
    "corresponde a otro gasto",
    "comprobante duplicado",
    "comprobante mal transcripto",
    "no es un pago de este gasto",
    "otro",
)


class ReviewNote(BaseModel):
    """Why a person rejected a link: for whoever fixes the data (`alas3 review-notes`)."""

    model_config = ConfigDict(extra="forbid")
    motivo: Literal[REJECT_REASONS]  # type: ignore[valid-type]
    detalle: str = Field(default="", max_length=2000)
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


OBSERVATION_KINDS = (
    "posible doble cobro",  # one receipt backing gastos in two months or two lines
    "sin comprobante",  # a gasto (or part of it) with no receipt
    "sin pago bancario",  # a gasto not paid from the consortium's account
    "pago sin gasto",  # a bank debit no gasto explains
    "comprobante repetido",  # the same receipt sent in two bundles
    "importe distinto",
    "otro",
)
OBSERVATION_STATES = ("abierta", "enviada", "respondida", "resuelta", "descartada")


class Observation(BaseModel):
    """An auditor's finding about the administration's accounts (data/work/observations.json).

    Published as is (every text through redact_text) to the site's "Observaciones" page:
    write it for the owners and the administrator, with evidence, never naming people."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")  # "<period>-<nn>", stable once published
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # the month it is about
    tipo: Literal[OBSERVATION_KINDS]  # type: ignore[valid-type]
    titulo: str = Field(min_length=1, max_length=200)
    detalle: str = Field(min_length=1, max_length=4000)  # es-AR, the arithmetic and the evidence
    importe: float | None = None  # amount at stake
    line_ids: list[int] = Field(default_factory=list)
    ticket_ids: list[int] = Field(default_factory=list)
    movement_ids: list[int] = Field(default_factory=list)
    estado: Literal[OBSERVATION_STATES] = "abierta"  # type: ignore[valid-type]
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")  # when it was raised
    respuesta: str = Field(default="", max_length=4000)  # the administrator's answer
    fecha_respuesta: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ObservationLog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[Observation] = Field(default_factory=list)


class AcceptedDiff(BaseModel):
    """A small difference the reviewer accepted on one side of a line (rounding, bank cents)."""

    model_config = ConfigDict(extra="forbid")
    importe: float = Field(gt=0)  # the side counts as complete while what is missing is <= this
    detalle: str = ""
    fecha: str  # YYYY-MM-DD


class ReviewState(BaseModel):
    """data/work/review.json: human decisions from `make review`, applied on publish."""

    model_config = ConfigDict(extra="forbid")
    # "<line_id>:<ticket_id>" -> decision. 'pending' = still to decide, kept as a proposal
    # when another receipt of the same proposal was rejected (otherwise the matcher, no
    # longer finding the sum, would drop the whole proposal).
    links: dict[str, Literal["verified", "rejected", "pending"]] = Field(default_factory=dict)
    tickets_verified: list[int] = Field(default_factory=list)
    lines_verified: list[int] = Field(default_factory=list)
    # "<line_id>:<movement_id>" -> decision (bank payments, see bank.py)
    payments: dict[str, Literal["verified", "rejected", "pending"]] = Field(default_factory=dict)
    # "link:<line_id>:<ticket_id>" / "payment:<line_id>:<movement_id>" -> why it was rejected
    notes: dict[str, ReviewNote] = Field(default_factory=dict)
    # Months ("YYYY-MM") the reviewer closed: their lines, receipts and bank movements
    # leave the review lists (until reopened). Review-only; publishing ignores it.
    closed_months: list[str] = Field(default_factory=list)
    # "<line_id>:receipt" / "<line_id>:payment" -> a small difference accepted by hand: that
    # side shows as complete in the review while the missing amount stays within it.
    accepted_diffs: dict[str, AcceptedDiff] = Field(default_factory=dict)

    def _pairs(self, decision: str) -> set[tuple[int, int]]:
        out = set()
        for k, v in self.links.items():
            if v == decision:
                a, b = k.split(":")
                out.add((int(a), int(b)))
        return out

    def verified_pairs(self) -> set[tuple[int, int]]:
        return self._pairs("verified")

    def rejected_pairs(self) -> set[tuple[int, int]]:
        return self._pairs("rejected")

    def held_pairs(self) -> set[tuple[int, int]]:
        return self._pairs("pending")
