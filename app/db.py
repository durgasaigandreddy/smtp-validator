import logging
import os
import time
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

log = logging.getLogger("db")
_pool = None

SCHEMA_PATH = Path(os.environ.get("SCHEMA_PATH") or Path(__file__).resolve().parent.parent / "sql" / "schema.sql")


def load_schema():
    try:
        return SCHEMA_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(f"Schema file not found: {SCHEMA_PATH}. Is the sql/ folder deployed?")


def pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL, min_size=1, max_size=10, open=True,
            kwargs={"row_factory": dict_row, "autocommit": True})
    return _pool


def q(sql, params=None, one=False):
    """Run one statement; return rows (or None for statements without output)."""
    with pool().connection() as conn:
        cur = conn.execute(sql, params)
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()


def init_db(retries=30):
    schema = load_schema()  # fail immediately (and clearly) if the file is missing
    for attempt in range(retries):
        try:
            with pool().connection() as conn:
                conn.execute("SELECT pg_advisory_lock(727)")
                try:
                    conn.execute(schema)
                finally:
                    conn.execute("SELECT pg_advisory_unlock(727)")
            return
        except Exception as e:
            log.warning("database not ready (%s), retrying", e)
            time.sleep(2)
    raise RuntimeError("database unavailable")
