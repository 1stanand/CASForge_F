"""
db/connection.py
----------------
Central database connection helper — uses a ThreadedConnectionPool for
efficient reuse under concurrent web API load.

Usage:
    from casforge.storage.connection import get_conn, release_conn, get_cursor

    conn = get_conn()
    try:
        with get_cursor(conn) as cur:
            cur.execute("SELECT 1")
        conn.commit()
    finally:
        release_conn(conn)   # returns connection to pool (DO NOT call conn.close())

Environment variables (loaded from .env at project root):
    DATABASE_NAME   - name of the PostgreSQL database
    DB_USER         - PostgreSQL username
    DB_PASSWORD     - PostgreSQL password
    DB_HOST         - host (default: localhost)
    DB_PORT         - port (default: 5432)
"""

import contextlib
from typing import Optional
import psycopg2
import psycopg2.extras
from psycopg2 import pool as psycopg2_pool

from casforge.shared.settings import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

# Connection parameters

_DSN = {
    "dbname":   DB_NAME,
    "user":     DB_USER,
    "password": DB_PASSWORD,
    "host":     DB_HOST,
    "port":     DB_PORT,
}

# ThreadedConnectionPool: min=1 keeps one warm connection ready,
# max=10 handles concurrent UI users without exhausting Postgres.
_pool: Optional[psycopg2_pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2_pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2_pool.ThreadedConnectionPool(minconn=1, maxconn=10, **_DSN)
    return _pool


# Public helpers

def get_conn() -> psycopg2.extensions.connection:
    """
    Return a connection from the pool.
    Caller MUST call release_conn(conn) when done to return it to the pool.
    Do NOT call conn.close() — psycopg2 does not override close() on pooled
    connections, so conn.close() physically closes the connection and leaks
    the pool slot.
    """
    conn = _get_pool().getconn()
    conn.autocommit = False
    return conn


def release_conn(conn) -> None:
    """
    Return a connection to the pool.
    Always call this in a finally block instead of conn.close().
    """
    _get_pool().putconn(conn)


@contextlib.contextmanager
def get_cursor(conn, *, dict_cursor: bool = True):
    """
    Yield a cursor from an existing connection.

    Args:
        conn:        An open psycopg2 connection.
        dict_cursor: If True (default), use RealDictCursor so rows are
                     accessible as dicts.  Set False for plain tuples.
    """
    factory = psycopg2.extras.RealDictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=factory)
    try:
        yield cur
    finally:
        cur.close()


def run_sql_file(path: str) -> None:
    """
    Execute every statement in a .sql file against the configured database.
    Useful for running schema.sql during setup.
    """
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()

    conn = get_conn()
    try:
        with get_cursor(conn, dict_cursor=False) as cur:
            cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)


def test_connection() -> bool:
    """
    Quick connectivity check. Returns True if the DB is reachable.
    """
    try:
        conn = get_conn()
        try:
            with get_cursor(conn) as cur:
                cur.execute("SELECT version()")
                row = cur.fetchone()
            print(f"[db] Connected OK - {row['version']}")
            return True
        finally:
            release_conn(conn)
    except Exception as exc:
        print(f"[db] Connection FAILED - {exc}")
        return False


if __name__ == "__main__":
    test_connection()
