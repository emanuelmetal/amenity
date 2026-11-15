"""Pydantic schemas for everything the pipeline produces (PLAN.md §4–5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class Liquidacion(BaseModel):
    period: str
    total: float | None = None
    rubro_totals: list[RubroTotal] = Field(default_factory=list)
    lines: list[LiquidacionLine]


class ReglamentoArticle(BaseModel):
    numero: str
    orden: int
    titulo: str | None = None
    texto: str
    page_nos: list[int]
    verified: bool = False


class Reglamento(BaseModel):
    articles: list[ReglamentoArticle]


# Defined now for Phase 2/3; not produced yet.
class TicketItem(BaseModel):
    descripcion: str
    cantidad: float | None = None
    importe: float | None = None


class Ticket(BaseModel):
    fecha: str | None = None
    proveedor: str | None = None
    cuit: str | None = None
    tipo_cmp: int | None = None
    pto_vta: int | None = None
    nro_cmp: int | None = None
    total: float | None = None
    medio_pago: str | None = None
    items: list[TicketItem] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    source: Literal["qr", "llm", "manual"] = "llm"
    confidence: float = 0.0


class ActaItem(BaseModel):
    tipo: Literal["decision", "tarea", "tema"]
    texto: str
    importe: float | None = None


class Acta(BaseModel):
    fecha: str
    resumen: str | None = None
    items: list[ActaItem] = Field(default_factory=list)
