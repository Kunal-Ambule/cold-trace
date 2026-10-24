"""Thin SQLite layer: one connection per thread, WAL mode, explicit SQL (no ORM magic to debug)."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import settings

_local = threading.local()
_SCHEMA = Path(__file__).with_name("schema.sql")


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    path = str(settings.db_path)
    if c is None or getattr(_local, "path", None) != path:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=10000")
        _local.conn, _local.path = c, path
    return c


def init_db() -> None:
    conn().executescript(_SCHEMA.read_text(encoding="utf-8"))


def reset_connections() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
    _local.conn = None


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    c = conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def one(sql: str, args: Iterable[Any] = ()) -> dict | None:
    r = conn().execute(sql, tuple(args)).fetchone()
    return dict(r) if r else None


def all_(sql: str, args: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, tuple(args)).fetchall()]


def run(sql: str, args: Iterable[Any] = ()) -> int:
    cur = conn().execute(sql, tuple(args))
    return cur.lastrowid or 0


def jdump(o: Any) -> str:
    return json.dumps(o, separators=(",", ":"), default=str)


def jload(s: str | None, default: Any = None) -> Any:
    return json.loads(s) if s else default
