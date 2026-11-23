import json

import pytest

from alas3 import ask_sync


def test_build_sql_quotes_and_replaces_each_table():
    sql = ask_sync.build_sql(
        {"ask_actas": [{"id": 1, "numero": None, "fecha": "2026-01-02", "tipo": "comision", "resumen": "O'Brien; DROP", "verificada": 1}]},
        {"ask_actas": ["id", "numero", "fecha", "tipo", "resumen", "verificada"]},
    )
    assert sql.startswith("DELETE FROM ask_actas;")
    assert "(1, NULL, '2026-01-02', 'comision', 'O''Brien; DROP', 1)" in sql


def test_build_sql_fails_closed():
    with pytest.raises(RuntimeError, match="no table"):
        ask_sync.build_sql({"ask_nueva": []}, {})
    with pytest.raises(RuntimeError, match="columns"):
        ask_sync.build_sql({"ask_actas": [{"id": 1, "secreto": "x"}]}, {"ask_actas": ["id"]})


def test_sync_reads_main_views_and_writes_only_the_ask_db(monkeypatch, tmp_path):
    monkeypatch.setattr(ask_sync, "OUT", tmp_path)
    commands: list[tuple[str, str]] = []

    def d1_command(sql, local, db="torre3"):
        commands.append((db, sql))
        if "type = 'view'" in sql:
            rows = [{"name": "ask_gastos_base"}, {"name": "ask_meses"}]
        elif "pragma_table_info" in sql:
            rows = [{"t": "ask_meses", "c": c} for c in ["mes", "anio"]]
        else:
            rows = [{"mes": "2026-10", "anio": 2026}]
        return json.dumps([{"results": rows}])

    files: list[tuple[str, str]] = []
    monkeypatch.setattr(ask_sync.wrangler, "d1_command", d1_command)
    monkeypatch.setattr(ask_sync.wrangler, "d1_file", lambda path, local, db="torre3": files.append((db, path.read_text())))
    ask_sync.sync(local=True)
    assert ("torre3", "SELECT * FROM ask_meses") in commands
    assert not any("ask_gastos_base" in sql for _, sql in commands if sql.startswith("SELECT *"))
    [(db, sql)] = files
    assert db == "torre3_ask"
    assert "INSERT INTO ask_meses (mes, anio) VALUES\n('2026-10', 2026);" in sql


def test_build_sql_splits_statements_by_size():
    cols = ["id", "texto"]
    rows = [{"id": i, "texto": "x" * 1000} for i in range(300)]
    sql = ask_sync.build_sql({"ask_articulos": rows}, {"ask_articulos": cols})
    stmts = [s for s in sql.split(";\n") if s.startswith("INSERT")]
    assert len(stmts) > 3
    assert all(len(s.encode()) <= ask_sync.MAX_STATEMENT for s in stmts)
    assert sum(s.count("\n(") + s.startswith("(") for s in stmts) == 300
    with pytest.raises(RuntimeError, match="exceeds"):
        ask_sync.build_sql({"ask_articulos": [{"id": 1, "texto": "x" * 100_000}]}, {"ask_articulos": cols})


def test_build_sql_empties_tables_without_a_view():
    sql = ask_sync.build_sql({}, {"ask_vieja": ["id"]})
    assert sql == "DELETE FROM ask_vieja;\n"


def _fake(monkeypatch, tmp_path, fail_file: bool):
    monkeypatch.setattr(ask_sync, "OUT", tmp_path)

    def d1_command(sql, local, db="torre3"):
        if "type = 'view'" in sql:
            rows = [{"name": "ask_meses"}]
        elif "pragma_table_info" in sql:
            rows = [{"t": "ask_meses", "c": "mes"}, {"t": "ask_actas", "c": "id"}]
        else:
            rows = [{"mes": "2026-10"}]
        return json.dumps([{"results": rows}])

    files: list[tuple[str, str]] = []

    def d1_file(path, local, db="torre3"):
        files.append((db, path.read_text()))
        if fail_file and path.name == "ask.sql":
            raise RuntimeError("wrangler failed")

    monkeypatch.setattr(ask_sync.wrangler, "d1_command", d1_command)
    monkeypatch.setattr(ask_sync.wrangler, "d1_file", d1_file)
    return files


def test_sync_failure_empties_every_ask_table(monkeypatch, tmp_path):
    files = _fake(monkeypatch, tmp_path, fail_file=True)
    with pytest.raises(RuntimeError, match="wrangler failed"):
        ask_sync.sync(local=True)
    assert files[-1] == ("torre3_ask", "DELETE FROM ask_actas;\nDELETE FROM ask_meses;\n")


def test_sync_mismatch_empties_every_ask_table(monkeypatch, tmp_path):
    files = _fake(monkeypatch, tmp_path, fail_file=False)
    monkeypatch.setattr(ask_sync.wrangler, "d1_command", lambda sql, local, db="torre3": json.dumps(
        [{"results": [{"name": "ask_nueva"}] if "type = 'view'" in sql else
          [{"t": "ask_meses", "c": "mes"}] if "pragma" in sql else [{"x": 1}]}]))
    with pytest.raises(RuntimeError, match="no table"):
        ask_sync.sync(local=True)
    assert files == [("torre3_ask", "DELETE FROM ask_meses;\n")]
