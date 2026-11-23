"""Tests use tiny PDFs generated on the fly; no real data is ever committed."""

from __future__ import annotations

import importlib
from pathlib import Path

import pymupdf
import pytest


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Points the pipeline at a temporary data/ tree."""
    monkeypatch.setenv("ALAS3_DATA", str(tmp_path))
    import alas3.config as config

    importlib.reload(config)
    for mod in (
        "alas3.actas",
        "alas3.ingest",
        "alas3.receipts",
        "alas3.extract",
        "alas3.review",
        "alas3.match",
        "alas3.publish",
    ):
        importlib.reload(importlib.import_module(mod))
    for folder in config.KIND_MAP:
        (tmp_path / "inbox" / folder).mkdir(parents=True)
    return tmp_path


def make_pdf(path: Path, pages: list[list[str] | list[tuple[str, str]]]) -> Path:
    """Each page is a list of lines; a tuple of 2 or 3 strings is drawn as table cells."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 72
        for line in lines:
            if isinstance(line, tuple):
                xs = (72, 420) if len(line) == 2 else (72, 250, 430)
                for x, cell in zip(xs, line, strict=True):
                    page.insert_text((x, y), cell, fontsize=10)
            else:
                page.insert_text((72, y), line, fontsize=10)
            y += 16
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
