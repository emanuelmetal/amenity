import pytest
from pydantic import ValidationError

from alas3.schemas import ObservationLog

CUIL = "20-12345678-3"


def _obs(**kw):
    base = dict(period="2026-09", tipo="sin comprobante", titulo="Falta factura", detalle="Sin respaldo.",
                fecha="2026-11-21")  # fmt: skip
    return {**base, **kw}


def test_ids_are_per_month_and_sequential():
    from alas3.observations import add

    log = ObservationLog()
    assert add(log, **_obs()).id == "2026-09-01"
    assert add(log, **_obs()).id == "2026-09-02"
    assert add(log, **_obs(period="2026-10")).id == "2026-10-01"


def test_rejects_unknown_kind_and_state():
    from alas3.observations import add

    with pytest.raises(ValidationError):
        add(ObservationLog(), **_obs(tipo="fraude"))
    with pytest.raises(ValidationError):
        add(ObservationLog(), **_obs(estado="cerrada"))


def test_load_refuses_repeated_ids(data_dir, monkeypatch):
    from alas3 import observations as obs

    log = ObservationLog()
    obs.add(log, **_obs())
    log.observations.append(log.observations[0])
    monkeypatch.setattr(obs, "OBSERVATIONS_FILE", data_dir / "work" / "observations.json")
    obs.save_observations(log)
    with pytest.raises(ValueError, match="repeated"):
        obs.load_observations()


def test_draft_lists_only_selected_states():
    from alas3.observations import add, draft

    log = ObservationLog()
    add(log, **_obs(titulo="Abierta", importe=1234.5))
    add(log, **_obs(titulo="Cerrada", estado="resuelta"))
    text = draft(log)
    assert "Abierta ($ 1.234,50)" in text and "Cerrada" not in text and "septiembre 2026" in text


def test_published_text_is_redacted_and_table_replaced():
    from alas3.observations import add
    from alas3.publish import build_sql
    from tests.test_pipeline import migrated_db

    log = ObservationLog()
    add(log, **_obs(detalle=f"Transferencia a CUIL {CUIL}", line_ids=[1, 2], respuesta="ok"))
    add(log, **_obs(titulo="No corresponde", estado="descartada"))  # kept in the log, never published
    sql = build_sql([], observations=log)
    assert "12345678" not in sql
    db = migrated_db()
    db.execute("INSERT INTO observations (id, period_id, tipo, titulo, detalle, estado, fecha) "
               "VALUES ('2020-01-01', '2020-01', 'otro', 'vieja', 'x', 'abierta', '2020-01-01')")  # fmt: skip
    db.executescript(sql)
    rows = db.execute("SELECT id, line_ids_json, respuesta FROM observations").fetchall()
    assert rows == [("2026-09-01", "[1, 2]", "ok")]
    assert "observations" not in build_sql([])  # no log given: published observations untouched
