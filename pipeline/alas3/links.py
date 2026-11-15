"""Access-link management (PLAN.md §3). The token is printed once and never stored.

new     --kind shared|unit|admin [--unit UF12] [--days N]
rotate  disable all active shared codes, print a new shared link.
        Sessions opened with the old link end immediately (the gate re-checks
        the code on every request), so everyone needs the new link.
revoke  --id N | --unit UF12
list
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets

from . import wrangler

LOCAL_URL = "http://localhost:8788"


def site_url(local: bool) -> str:
    if local:
        return LOCAL_URL
    url = os.environ.get("ALAS3_SITE_URL", "").rstrip("/")
    if not url.startswith("https://"):
        raise SystemExit("Set ALAS3_SITE_URL=https://<your-site> to create links for the real site.")
    return url


def new_token() -> tuple[str, str]:
    """Returns (token, sha256 hex). 32 random bytes → 43 base64url chars."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def _unit(label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9 _-]{1,20}", label):
        raise SystemExit("unit label: letters, digits, space, _ or - (max 20)")
    return label


def insert_sql(code_hash: str, kind: str, unit: str | None, days: int | None) -> str:
    assert re.fullmatch(r"[0-9a-f]{64}", code_hash) and kind in ("shared", "unit", "admin")
    unit_sql = f"'{_unit(unit)}'" if unit else "NULL"
    exp = f"datetime('now', '+{int(days)} days')" if days else "NULL"
    return (
        f"INSERT INTO access_codes (code_hash, kind, unit_label, expires_at) "
        f"VALUES ('{code_hash}', '{kind}', {unit_sql}, {exp});"
    )


def create(kind: str, unit: str | None, days: int | None, local: bool, extra_sql: str = "") -> str:
    if kind == "unit" and not unit:
        raise SystemExit("--unit is required for kind=unit")
    base = site_url(local)  # fail before touching the database
    token, h = new_token()
    wrangler.d1_command(extra_sql + insert_sql(h, kind, unit, days), local)
    return f"{base}/acceso?k={token}"


def rotate(local: bool) -> str:
    return create(
        "shared", None, None, local, extra_sql="UPDATE access_codes SET active = 0 WHERE kind = 'shared';"
    )


def revoke(local: bool, code_id: int | None, unit: str | None) -> None:
    if code_id is not None:
        wrangler.d1_command(f"UPDATE access_codes SET active = 0 WHERE id = {int(code_id)};", local)
    elif unit:
        wrangler.d1_command(f"UPDATE access_codes SET active = 0 WHERE unit_label = '{_unit(unit)}';", local)
    else:
        raise SystemExit("revoke needs --id or --unit")


def list_codes(local: bool) -> None:
    out = wrangler.d1_command(
        "SELECT id, kind, unit_label, active, created_at, expires_at, last_used_at, uses "
        "FROM access_codes ORDER BY id;",
        local,
    )
    rows = json.loads(out)[0]["results"]
    for r in rows:
        print(
            f"#{r['id']:<4} {r['kind']:<7} {r['unit_label'] or '':<8} {'activo' if r['active'] else 'inactivo':<9}"
            f" usos={r['uses']:<4} último={r['last_used_at'] or '—'} vence={r['expires_at'] or '—'}"
        )
