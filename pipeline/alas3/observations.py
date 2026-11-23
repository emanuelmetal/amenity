"""The auditor's log of observations about the administration (CLAUDE.md, "Role: auditor").

data/work/observations.json (schemas.ObservationLog) is the source of truth: one entry per
finding, appended month after month, never deleted (a finding that turns out fine is
`descartada`, one the administrator fixed is `resuelta`). Every entry is published to the
site's "Observaciones" page (publish.py); `alas3 observations --draft` prints the open ones as
a message for the administrator.
"""

from __future__ import annotations

from .config import WORK
from .schemas import Observation, ObservationLog

OBSERVATIONS_FILE = WORK / "observations.json"


def load_observations() -> ObservationLog:
    if not OBSERVATIONS_FILE.exists():
        return ObservationLog()
    log = ObservationLog.model_validate_json(OBSERVATIONS_FILE.read_text())  # fails loudly on bad input
    ids = [o.id for o in log.observations]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{OBSERVATIONS_FILE}: repeated observation ids")
    return log


def save_observations(log: ObservationLog) -> None:
    OBSERVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OBSERVATIONS_FILE.with_suffix(".tmp")
    tmp.write_text(log.model_dump_json(indent=1, exclude_defaults=False))
    tmp.replace(OBSERVATIONS_FILE)


def next_id(log: ObservationLog, period: str) -> str:
    n = max((int(o.id[-2:]) for o in log.observations if o.id.startswith(period + "-")), default=0)
    return f"{period}-{n + 1:02d}"


def add(log: ObservationLog, **fields) -> Observation:
    """Append a new observation with the next id of its month."""
    obs = Observation(id=next_id(log, fields["period"]), **fields)
    log.observations.append(obs)
    return obs


def _money(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


_MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


def month_label(period: str) -> str:
    y, m = period.split("-")
    return f"{_MONTHS[int(m) - 1]} {y}"


def draft(log: ObservationLog, estados: tuple[str, ...] = ("abierta",), period: str | None = None) -> str:
    """The selected observations as a plain-text message for the administrator (es-AR)."""
    obs = [o for o in log.observations if o.estado in estados and (period is None or o.period == period)]
    if not obs:
        return "No hay observaciones con ese filtro."
    out = [
        "Observaciones sobre la rendición de gastos de Torre 3",
        "",
        "Solicitamos la documentación respaldatoria o la aclaración de los siguientes puntos "
        "(art. 2067 inc. e y arts. 858 a 864 del Código Civil y Comercial):",
    ]
    for p in sorted({o.period for o in obs}):
        out += ["", f"== {month_label(p)} =="]
        for o in (x for x in obs if x.period == p):
            amount = f" ({_money(o.importe)})" if o.importe is not None else ""
            out += ["", f"{o.id} · {o.tipo}: {o.titulo}{amount}", o.detalle]
    return "\n".join(out) + "\n"


def report(log: ObservationLog) -> str:
    rows = [
        f"{o.id}  {o.estado:<10} {o.tipo:<22} {(_money(o.importe) if o.importe is not None else ''):>16}  {o.titulo}"
        for o in sorted(log.observations, key=lambda o: o.id)
    ]
    return "\n".join(rows) if rows else "No observations yet (data/work/observations.json)."
