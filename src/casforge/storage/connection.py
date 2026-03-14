"""
db/connection.py
----------------
Central database connection helper.

Usage:
    from casforge.storage.connection import get_conn, get_cursor

    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT 1")

Environment variables (loaded from .env at project root):
    DATABASE_NAME   â€” name of the PostgreSQL database
    DB_USER         â€” PostgreSQL username
    DB_PASSWORD     â€” PostgreSQL password
    DB_HOST         â€” host (default: localhost)
    DB_PORT         â€” port (default: 5432)
"""

import contextlib
import psycopg2
import psycopg2.extras

from casforge.shared.settings import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

# â”€â”€ Connection parameters â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_DSN = {
    "dbname":   DB_NAME,
    "user":     DB_USER,
    "password": DB_PASSWORD,
    "host":     DB_HOST,
    "port":     DB_PORT,
}


# â”€â”€ Public helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_conn() -> psycopg2.extensions.connection:
    """
    Return a new psycopg2 connection.
    Caller is responsible for commit / rollback / close.
    Prefer the context manager form (with get_conn() as conn).
    """
    conn = psycopg2.connect(**_DSN)
    conn.autocommit = False
    return conn


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

    Args:
        path: Absolute or relative path to the .sql file.
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
        conn.close()


def test_connection() -> bool:
    """
    Quick connectivity check.  Returns True if the DB is reachable.
    Prints the PostgreSQL server version on success.
    """
    try:
        conn = get_conn()
        with get_cursor(conn) as cur:
            cur.execute("SELECT version()")
            row = cur.fetchone()
        conn.close()
        print(f"[db] Connected OK â€” {row['version']}")
        return True
    except Exception as exc:
        print(f"[db] Connection FAILED â€” {exc}")
        return False


if __name__ == "__main__":
    test_connection()


