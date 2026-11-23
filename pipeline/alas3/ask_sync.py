"""Copies the ask_* views of the main D1 database into the `torre3_ask` database (Phase 4).

"Preguntale al portal" (web/server/ask.ts) runs LLM-written SQL only against `torre3_ask`,
which holds nothing but these copies (db/ask_migrations). The views in the main database
(db/migrations/0009_ask.sql) stay the single definition of what is exposed; this module only
reads them after a publish and replaces the copy, table by table. A view the ask database
has no table for is an error (fail closed: nothing is copied anywhere it was not declared).
If the copy fails, every ask table is emptied, so the site never answers from a stale copy
(e.g. an observation or receipt withdrawn by this publish); an ask table whose view was
dropped is emptied too.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import wrangler
from .config import ASK_DB_NAME, DB_NAME, OUT

# Not offered to the model (an intermediate view of ask_gastos).
SKIP_VIEWS = {"ask_gastos_base"}
# D1 refuses statements over 100 KB; keep each INSERT well under it.
MAX_STATEMENT = 90_000


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


def _inserts(name: str, cols: list[str], rows: list[dict]) -> list[str]:
    head = f"INSERT INTO {name} ({', '.join(cols)}) VALUES\n"
    out: list[str] = []
    values: list[str] = []
    size = len(head)
    for r in rows:
        if set(r) != set(cols):
            raise RuntimeError(f"{name}: view columns {sorted(r)} != table columns {sorted(cols)}")
        v = "(" + ", ".join(_q(r[c]) for c in cols) + ")"
        if len(head) + len(v.encode()) + 2 > MAX_STATEMENT:
            raise RuntimeError(f"{name}: row {r.get('id')} alone exceeds {MAX_STATEMENT} bytes")
        if values and size + len(v.encode()) + 2 > MAX_STATEMENT:
            out.append(head + ",\n".join(values) + ";")
            values, size = [], len(head)
        values.append(v)
        size += len(v.encode()) + 2
    if values:
        out.append(head + ",\n".join(values) + ";")
    return out


def build_sql(tables: dict[str, list[dict]], columns: dict[str, list[str]]) -> str:
    """DELETE + INSERT for each ask table. `columns` = the ask database's columns per table.
    Ask tables with no source view are emptied (a view dropped to stop exposing something)."""
    out: list[str] = []
    for name, rows in tables.items():
        if name not in columns:
            raise RuntimeError(f"{name}: no table in {ASK_DB_NAME} (add it to db/ask_migrations)")
        out.append(f"DELETE FROM {name};")
        out.extend(_inserts(name, columns[name], rows))
    for name in sorted(set(columns) - set(tables)):
        print(f"  warning: {ASK_DB_NAME}.{name} has no ask_* view in {DB_NAME}; emptied (drop it in db/ask_migrations)")
        out.append(f"DELETE FROM {name};")
    return "\n".join(out) + "\n"


def clear_sql(columns: dict[str, list[str]]) -> str:
    return "".join(f"DELETE FROM {name};\n" for name in sorted(columns))


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
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        tables = {v: _rows(wrangler.d1_command(f"SELECT * FROM {v}", local)) for v in views}
        path: Path = OUT / "ask.sql"
        path.write_text(build_sql(tables, columns))
        wrangler.d1_file(path, local, db=ASK_DB_NAME)
    except Exception:
        # Never leave the previous copy behind: it may hold rows this publish withdrew.
        empty = OUT / "ask_clear.sql"
        empty.write_text(clear_sql(columns))
        wrangler.d1_file(empty, local, db=ASK_DB_NAME)
        print(f"  {ASK_DB_NAME}: copy failed, all ask tables emptied (Preguntale al portal has no data until the next publish)")
        raise
    print(f"  {ASK_DB_NAME}: {sum(len(r) for r in tables.values())} rows in {len(tables)} tables ({DB_NAME} ask_* views)")
