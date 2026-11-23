"""Thin wrapper around the wrangler CLI installed in web/."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import BUCKET, DB_NAME, WEB


def _run(args: list[str]) -> str:
    res = subprocess.run(["pnpm", "exec", "wrangler", *args], cwd=WEB, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"wrangler {' '.join(args[:3])} failed:\n{res.stderr or res.stdout}")
    return res.stdout


def target_flag(local: bool) -> str:
    return "--local" if local else "--remote"


def d1_file(path: Path, local: bool, db: str = DB_NAME) -> None:
    _run(["d1", "execute", db, target_flag(local), "--yes", "--file", str(path)])


def d1_command(sql: str, local: bool, db: str = DB_NAME) -> str:
    return _run(["d1", "execute", db, target_flag(local), "--yes", "--json", "--command", sql])


def r2_put(key: str, file: Path, content_type: str, local: bool) -> None:
    _run(
        [
            "r2",
            "object",
            "put",
            f"{BUCKET}/{key}",
            "--file",
            str(file),
            "--content-type",
            content_type,
            target_flag(local),
        ]
    )


def r2_delete(key: str, local: bool) -> None:
    _run(["r2", "object", "delete", f"{BUCKET}/{key}", target_flag(local)])
