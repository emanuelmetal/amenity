"""Step 4: structured extraction (Phase 1: reglamento + liquidaciones, deterministic).

Output: data/work/docs/<sha16>/extract.json (Reglamento | Liquidacion).

Escape hatch (PLAN.md §4 option A): if data/work/extract/<sha16>.json exists it
is used instead of the parser (e.g. written by Claude Code from the page
images). It must validate against the same schema.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from . import liquidacion
from .config import WORK
from .ingest import doc_dir, raw_text
from .schemas import Comprobantes, DocumentManifest, Liquidacion, Reglamento, ReglamentoArticle

MANUAL_DIR = WORK / "extract"

# "ARTÍCULO 12°.- Título", "Artículo 3: ...", "ART. 4 -", "ARTICULO PRIMERO:"
_ARTICLE_RE = re.compile(
    r"^\s*ART(?:[IÍ]CULO|\.)\s+(?P<num>\d+(?:\s*bis)?|[A-ZÁÉÍÓÚ]+)\s*[°º]?\s*(?:[.\-–—:)]+\s*)?(?P<rest>.*)$",
    re.IGNORECASE,
)


def parse_reglamento(pages: list[tuple[int, str]]) -> Reglamento:
    """pages: [(page_no, raw_text)] in order."""
    articles: list[ReglamentoArticle] = []
    current: dict | None = None

    def close() -> None:
        if current is None:
            return
        body = _clean("\n".join(current["lines"]))
        titulo = current["titulo"]
        # Short first sentence ending in '.' right after the number reads as a title.
        if not titulo and body:
            first, _, rest = body.partition("\n")
            if len(first) <= 80 and rest:
                titulo, body = first.rstrip(".:"), rest.strip()
        articles.append(
            ReglamentoArticle(
                numero=current["numero"],
                orden=len(articles) + 1,
                titulo=titulo or None,
                texto=body,
                page_nos=sorted(current["pages"]),
            )
        )

    for page_no, text in pages:
        for line in text.splitlines():
            m = _ARTICLE_RE.match(line)
            if m:
                close()
                rest = m.group("rest").strip()
                # "ARTICULO 5°.- DE LAS COCHERAS. Las cocheras..." → title = upper-case lead-in
                titulo = None
                tm = re.match(r"^([A-ZÁÉÍÓÚÑ ,]{4,80})[.:]\s*(.*)$", rest)
                if tm:
                    titulo, rest = tm.group(1).strip().capitalize(), tm.group(2)
                current = {
                    "numero": m.group("num").strip().upper(),
                    "titulo": titulo,
                    "lines": [rest],
                    "pages": {page_no},
                }
            elif current is not None:
                current["lines"].append(line)
                if line.strip():
                    current["pages"].add(page_no)
    close()
    return Reglamento(articles=articles)


def _clean(text: str) -> str:
    """Join hard-wrapped lines into paragraphs; drop page-number-only lines."""
    paragraphs: list[str] = []
    buf = ""
    for ln in (ln.strip() for ln in text.splitlines()):
        if re.fullmatch(r"(p[aá]g(ina)?\.?\s*)?\d{1,3}", ln, re.I):
            continue
        if not ln:
            if buf:
                paragraphs.append(buf)
                buf = ""
        elif buf.endswith("-"):
            buf = buf[:-1] + ln  # hyphenated word split across lines
        elif buf.endswith((".", ":", ";")) and ln[:1].isupper():
            paragraphs.append(buf)  # likely a new paragraph without a blank line
            buf = ln
        else:
            buf = f"{buf} {ln}" if buf else ln
    if buf:
        paragraphs.append(buf)
    return "\n".join(paragraphs)


def extract_document(m: DocumentManifest) -> BaseModel | None:
    stale = doc_dir(m) / "extract.json"
    stale.unlink(missing_ok=True)  # a failed extraction must never leave an old result to be published
    manual = MANUAL_DIR / f"{m.work_dir_name}.json"
    pages = [(p.page_no, raw_text(m, p.page_no)) for p in m.pages if not p.restricted]
    result: BaseModel | None
    if m.kind == "reglamento":
        result = (
            Reglamento.model_validate_json(manual.read_text()) if manual.exists() else parse_reglamento(pages)
        )
    elif m.kind == "liquidacion":
        if manual.exists():
            result = Liquidacion.model_validate_json(manual.read_text())
        else:
            if not m.period:
                raise ValueError(f"{m.source_name}: cannot infer period (name files YYYY-MM_*.pdf)")
            result = liquidacion.parse(m.period, pages)
    elif m.kind == "comprobantes":
        from . import receipts

        result = receipts.build(m)
    else:
        return None  # actas: Phase 3
    out: Path = doc_dir(m) / "extract.json"
    out.write_text(result.model_dump_json(indent=2))
    return result


def load_extract(m: DocumentManifest) -> dict | None:
    p = doc_dir(m) / "extract.json"
    if not p.exists():
        return None
    model = {"reglamento": Reglamento, "liquidacion": Liquidacion, "comprobantes": Comprobantes}.get(m.kind)
    return model.model_validate_json(p.read_text()) if model else None  # type: ignore[return-value]
