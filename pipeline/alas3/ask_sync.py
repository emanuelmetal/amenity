"""Copies the ask_* views of the main D1 database into the `torre3_ask` database (Phase 4).

"Preguntale al portal" (web/server/ask.ts) runs LLM-written SQL only against `torre3_ask`,
which holds nothing but these copies (db/ask_migrations). The views in the main database
(db/migrations/0009_ask.sql) stay the single definition of what is exposed; this module only
reads them after a publish and replaces the copy, table by table. A view the ask database
has no table for is an error (fail closed: nothing is copied anywhere it was not declared).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import wrangler
from .config import ASK_DB_NAME, DB_NAME, OUT

# Not offered to the model (an intermediate view of ask_gastos).
SKIP_VIEWS = {"ask_gastos_base"}
BATCH = 200


def _rows(output: str) -> list[dict]:
    data = json.loads(output)
    return data[0]["results"] if isinstance(data, list) else data["results"]


def _q(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int | float):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def build_sql(tables: dict[str, list[dict]], columns: dict[str, list[str]]) -> str:
    """DELETE + INSERT for each ask table. `columns` = the ask database's columns per table."""
    out: list[str] = []
    for name, rows in tables.items():
        if name not in columns:
            raise RuntimeError(f"{name}: no table in {ASK_DB_NAME} (add it to db/ask_migrations)")
        cols = columns[name]
        out.append(f"DELETE FROM {name};")
        for i in range(0, len(rows), BATCH):
            chunk = rows[i : i + BATCH]
            for r in chunk:
                if set(r) != set(cols):
                    raise RuntimeError(f"{name}: view columns {sorted(r)} != table columns {sorted(cols)}")
            values = ",\n".join("(" + ", ".join(_q(r[c]) for c in cols) + ")" for r in chunk)
            out.append(f"INSERT INTO {name} ({', '.join(cols)}) VALUES\n{values};")
    return "\n".join(out) + "\n"


def sync(local: bool) -> None:
    views = [
        r["name"]
        for r in _rows(
            wrangler.d1_command(
                "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'ask\\_%' ESCAPE '\\' ORDER BY name",
                local,
            )
        )
        if r["name"] not in SKIP_VIEWS
    ]
    columns: dict[str, list[str]] = {}
    for r in _rows(
        wrangler.d1_command(
            "SELECT m.name AS t, p.name AS c FROM sqlite_master m, pragma_table_info(m.name) p "
            "WHERE m.type = 'table' AND m.name LIKE 'ask\\_%' ESCAPE '\\' ORDER BY m.name, p.cid",
            local,
            db=ASK_DB_NAME,
        )
    ):
        columns.setdefault(r["t"], []).append(r["c"])
    tables = {v: _rows(wrangler.d1_command(f"SELECT * FROM {v}", local)) for v in views}
    OUT.mkdir(parents=True, exist_ok=True)
    path: Path = OUT / "ask.sql"
    path.write_text(build_sql(tables, columns))
    wrangler.d1_file(path, local, db=ASK_DB_NAME)
    print(f"  {ASK_DB_NAME}: {sum(len(r) for r in tables.values())} rows in {len(tables)} tables ({DB_NAME} ask_* views)")
