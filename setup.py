"""
setup.py
--------
One-command project setup for CASForge.

Steps performed:
  1. Test PostgreSQL connection
  2. Create the database (if it does not already exist)
  3. Apply src/casforge/storage/schema.sql  (drops + recreates all tables)
  4. Ingest feature files from FEATURES_REPO_PATH (.env)
  5. Build FAISS vector index

All configuration is in .env â€” set FEATURES_REPO_PATH before running.

Usage
-----
    python setup.py
    setup.bat
"""

import os
import sys

import psycopg2
import psycopg2.extensions

from casforge.shared.settings import (
    DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT,
    FEATURES_REPO_PATH, SCHEMA_PATH,
)

# -----------------------------------------------------------------------------

DB_PASS      = DB_PASSWORD
_SCHEMA_PATH = SCHEMA_PATH

SEP = "-" * 60


def _print(msg: str):
    print(f"  {msg}")


def _ok(msg: str):
    print(f"  [OK]  {msg}")


def _fail(msg: str):
    print(f"  [FAIL] {msg}")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Step 1 - Test connection to PostgreSQL server (not to DB yet)
# -----------------------------------------------------------------------------

def step_test_connection():
    print(SEP)
    print("Step 1 - Testing PostgreSQL connection ...")
    try:
        conn = psycopg2.connect(
            dbname="postgres",   # connect to default DB to check server
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
        )
        cur = conn.cursor()
        cur.execute("SELECT version()")
        ver = cur.fetchone()[0]
        cur.close()
        conn.close()
        _ok(f"Connected - {ver[:60]}")
    except Exception as exc:
        _fail(
            f"Cannot connect to PostgreSQL: {exc}\n"
            f"       Check .env - DB_USER={DB_USER}  DB_HOST={DB_HOST}  DB_PORT={DB_PORT}"
        )


# -----------------------------------------------------------------------------
# Step 2 - Create database if it does not exist
# -----------------------------------------------------------------------------

def step_create_database():
    print(SEP)
    print(f"Step 2 - Ensuring database '{DB_NAME}' exists ...")
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=DB_USER,
            password=DB_PASS,
            host=DB_HOST,
            port=DB_PORT,
        )
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if exists:
            _ok(f"Database '{DB_NAME}' already exists - skipping creation.")
        else:
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
            _ok(f"Database '{DB_NAME}' created.")

        cur.close()
        conn.close()
    except Exception as exc:
        _fail(f"Failed to create database: {exc}")


# -----------------------------------------------------------------------------
# Step 3 - Apply schema
# -----------------------------------------------------------------------------

def step_apply_schema():
    print(SEP)
    print("Step 3 - Applying schema (drops + recreates all tables) ...")
    try:
        from casforge.storage.connection import run_sql_file
        run_sql_file(_SCHEMA_PATH)
        _ok("Schema applied - tables created.")
    except Exception as exc:
        _fail(f"Schema apply failed: {exc}")


# -----------------------------------------------------------------------------
# Step 4 - Ingest feature files
# -----------------------------------------------------------------------------

def step_ingest():
    print(SEP)
    if not FEATURES_REPO_PATH:
        _print("FEATURES_REPO_PATH is not set in .env â€” skipping ingest.")
        _print("Set it and re-run setup.bat, or run ingest_incremental.bat later.")
        return

    print(f"Step 4 - Ingesting feature files from: {FEATURES_REPO_PATH}")
    if not os.path.isdir(FEATURES_REPO_PATH):
        _fail(f"FEATURES_REPO_PATH does not exist: {FEATURES_REPO_PATH}")

    from tools.cli.ingest import run_ingest
    try:
        run_ingest(FEATURES_REPO_PATH, full_rebuild=False)
        _ok("Ingest complete.")
    except SystemExit:
        pass   # run_ingest calls sys.exit on error - already printed
    except Exception as exc:
        _fail(f"Ingest failed: {exc}")


# -----------------------------------------------------------------------------
# Step 5 - Build vector index
# -----------------------------------------------------------------------------

def step_build_index():
    print(SEP)
    print("Step 5 - Building FAISS vector index ...")
    print("         (downloads ~90 MB model on first run - needs internet once)")
    try:
        from casforge.storage.connection import get_conn, get_cursor
        from casforge.retrieval.embedder import build_index

        conn = get_conn()
        with get_cursor(conn) as cur:
            cur.execute("SELECT id, step_text FROM unique_steps ORDER BY id")
            rows = cur.fetchall()
        conn.close()

        if not rows:
            _print("No steps in DB - skipping index build.")
            _print("Run:  python tools/cli/ingest.py  then  python tools/cli/build_index.py")
            return

        build_index([{"id": r["id"], "step_text": r["step_text"]} for r in rows])
        _ok(f"Vector index built - {len(rows)} unique steps indexed.")
    except Exception as exc:
        _fail(f"Index build failed: {exc}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    print()
    print("=" * 60)
    print("  CASForge - Setup")
    print("=" * 60)

    step_test_connection()
    step_create_database()
    step_apply_schema()
    step_ingest()

    if FEATURES_REPO_PATH:
        step_build_index()

    print(SEP)
    print("  Setup complete.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()





