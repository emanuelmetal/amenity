"""Pydantic schemas for everything the pipeline produces (PLAN.md §4–5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class Liquidacion(BaseModel):
    period: str
    total: float | None = None
    rubro_totals: list[RubroTotal] = Field(default_factory=list)
    lines: list[LiquidacionLine]
    resumen: Resumen | None = None


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
    period: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")
    subcategoria: str | None = None
    tags: list[str] = Field(default_factory=list)
    verified: bool = False

    def key(self) -> tuple | None:
        """Identity of a fiscal voucher (the same invoice in ORIGINAL/DUPLICADO copies)."""
        if self.pto_vta is None or self.nro_cmp is None:
            return None
        return (self.cuit and self.cuit.replace("-", ""), self.tipo_cmp, self.pto_vta, self.nro_cmp)


class TicketTranscription(BaseModel):
    """data/work/extract/<sha16>.tickets.json: hand/Claude transcription of a receipts PDF."""

    model_config = ConfigDict(extra="forbid")
    tickets: list[Ticket] = Field(default_factory=list)
    # Pages that hold no receipt, with what they are ("extracto bancario", "contrato", ...).
    other_pages: dict[int, str] = Field(default_factory=dict)


class BankItem(BaseModel):
    """One concept of a grouped charge ("IMPUESTO LEY 25413" x 41)."""

    descripcion: str
    importe: float  # positive: money that left the account
    cantidad: int = 1


class BankMovement(BaseModel):
    """A debit of the consortium's bank account: evidence that an expense was paid.

    kind 'debito' = one outgoing movement (transfer, direct debit); 'gastos' = every
    commission and tax of the statement grouped into one (the "gastos bancarios" line).
    Credits (owners' expensas payments) are never stored one by one.
    """

    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    comprobante: str | None = None
    codigo: str | None = None
    descripcion: str
    importe: float  # positive: money that left the account
    kind: Literal["debito", "gastos"] = "debito"
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


class ActaItem(BaseModel):
    tipo: Literal["decision", "tarea", "tema"]
    texto: str
    importe: float | None = None


class Acta(BaseModel):
    fecha: str
    resumen: str | None = None
    items: list[ActaItem] = Field(default_factory=list)


class ReviewState(BaseModel):
    """data/work/review.json: human decisions from `make review`, applied on publish."""

    model_config = ConfigDict(extra="forbid")
    # "<line_id>:<ticket_id>" -> decision
    links: dict[str, Literal["verified", "rejected"]] = Field(default_factory=dict)
    tickets_verified: list[int] = Field(default_factory=list)
    lines_verified: list[int] = Field(default_factory=list)
    # "<line_id>:<movement_id>" -> decision (bank payments, see bank.py)
    payments: dict[str, Literal["verified", "rejected"]] = Field(default_factory=dict)

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
