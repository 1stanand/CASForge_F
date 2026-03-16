"""
scripts/ingest.py
-----------------
Incremental feature-file ingestion pipeline.

Repo path is read from FEATURES_REPO_PATH in .env â€” no CLI argument needed.

Usage
-----
Incremental (default â€” only new / changed / deleted files):
    python scripts/ingest.py

Full rebuild (drop + recreate schema, re-parse everything):
    python scripts/ingest.py --full-rebuild
"""

import argparse
import glob
import json
import logging
import os
import sys
import time

# â”€â”€ Make project root importable â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from casforge.storage.connection import get_conn, release_conn, get_cursor, run_sql_file
from casforge.parsing.feature_parser import parse_file
from casforge.shared.paths import resolve_user_path
from casforge.shared.settings import FEATURES_REPO_PATH, SCHEMA_PATH

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SCHEMA_PATH = SCHEMA_PATH


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# DB helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def db_fetch_all_mtimes(conn) -> dict:
    """Return {file_path: file_mtime} for every row in features table."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT file_path, file_mtime FROM features")
        return {row["file_path"]: row["file_mtime"] for row in cur.fetchall()}


def db_delete_feature(conn, file_path: str) -> None:
    """Delete a features row (CASCADE removes all child rows)."""
    with get_cursor(conn) as cur:
        cur.execute("DELETE FROM features WHERE file_path = %s", (file_path,))
    conn.commit()


def db_insert_feature(conn, parsed: dict, mtime: float) -> None:
    """
    Insert a fully parsed feature into the DB.
    Uses a single transaction â€” rolls back on any error.
    """
    try:
        with get_cursor(conn) as cur:
            # â”€â”€ features â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            cur.execute(
                """
                INSERT INTO features
                    (file_path, file_name, feature_title,
                     file_annotations, file_dicts,
                     is_order_file, is_e2e_order, has_conflict,
                     parse_error, file_mtime)
                VALUES (%s,%s,%s, %s,%s::jsonb, %s,%s,%s, %s,%s)
                RETURNING id
                """,
                (
                    parsed["file_path"],
                    parsed["file_name"],
                    parsed["feature_title"],
                    parsed["file_annotations"],
                    json.dumps(parsed["file_dicts"]),
                    parsed["is_order_file"],
                    parsed["is_e2e_order"],
                    parsed["has_conflict"],
                    parsed["parse_error"],
                    mtime,
                )
            )
            feature_id = cur.fetchone()["id"]

            # â”€â”€ scenarios â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            for sc in parsed["scenarios"]:
                cur.execute(
                    """
                    INSERT INTO scenarios
                        (feature_id, title, is_outline,
                         scenario_annotations, scenario_dicts, scenario_index)
                    VALUES (%s,%s,%s, %s,%s::jsonb,%s)
                    RETURNING id
                    """,
                    (
                        feature_id,
                        sc["title"],
                        sc["is_outline"],
                        sc["scenario_annotations"],
                        json.dumps(sc["scenario_dicts"]),
                        sc["scenario_index"],
                    )
                )
                scenario_id = cur.fetchone()["id"]

                # â”€â”€ steps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if sc["steps"]:
                    # Build values list for executemany
                    step_rows = [
                        (
                            scenario_id,
                            s["keyword"],
                            s["step_text"],
                            s["step_position"],
                            s.get("screen_context"),
                        )
                        for s in sc["steps"]
                    ]
                    cur.executemany(
                        """
                        INSERT INTO steps
                            (scenario_id, keyword, step_text,
                             step_position, screen_context)
                        VALUES (%s,%s,%s,%s,%s)
                        """,
                        step_rows
                    )

                # â”€â”€ example_blocks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                for eb in sc["example_blocks"]:
                    cur.execute(
                        """
                        INSERT INTO example_blocks
                            (scenario_id, block_annotations, block_dicts,
                             headers, rows, block_index)
                        VALUES (%s,%s,%s::jsonb,%s,%s::jsonb,%s)
                        """,
                        (
                            scenario_id,
                            eb["block_annotations"],
                            json.dumps(eb["block_dicts"]),
                            eb["headers"],
                            json.dumps(eb["rows"]),
                            eb["block_index"],
                        )
                    )

        conn.commit()

    except Exception:
        conn.rollback()
        raise


def db_refresh_unique_steps(conn) -> None:
    """Refresh the unique_steps materialised view after ingest."""
    with get_cursor(conn, dict_cursor=False) as cur:
        cur.execute("REFRESH MATERIALIZED VIEW unique_steps")
    conn.commit()


def db_total_counts(conn) -> dict:
    """Return dict with total row counts for the summary line."""
    with get_cursor(conn) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM features")
        n_files = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM scenarios")
        n_scen = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM steps")
        n_steps = cur.fetchone()["n"]
    return {"files": n_files, "scenarios": n_scen, "steps": n_steps}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# File discovery
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def find_feature_files(repo_path: str) -> list[str]:
    """Recursively find all .feature files under repo_path."""
    pattern = os.path.join(repo_path, "**", "*.feature")
    return [
        os.path.normpath(p)
        for p in glob.glob(pattern, recursive=True)
    ]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Main ingest logic
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_ingest(repo_path: str, full_rebuild: bool = False) -> None:
    repo_path = os.path.normpath(str(resolve_user_path(repo_path)))
    if not os.path.isdir(repo_path):
        logger.error("repo-path does not exist: %s", repo_path)
        sys.exit(1)

    conn = get_conn()

    # â”€â”€ Full rebuild: drop + recreate schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if full_rebuild:
        logger.info("Full rebuild requested â€” running schema.sql ...")
        run_sql_file(_SCHEMA_PATH)
        logger.info("Schema recreated.")

    # â”€â”€ Discover files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("Scanning %s ...", repo_path)
    disk_files_list = find_feature_files(repo_path)
    disk_files = set(disk_files_list)
    logger.info("Found %d .feature files.", len(disk_files))

    # â”€â”€ Load existing mtimes from DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    existing = db_fetch_all_mtimes(conn)

    # â”€â”€ Categorise â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    new_files:     list[str] = []
    changed_files: list[str] = []
    deleted_files: list[str] = []

    for fpath in disk_files:
        mtime = os.path.getmtime(fpath)
        if fpath not in existing:
            new_files.append(fpath)
        elif abs(existing[fpath] - mtime) > 0.001:   # float tolerance
            changed_files.append(fpath)
        # else: unchanged â€” skip

    for fpath in existing:
        if fpath not in disk_files:
            deleted_files.append(fpath)

    unchanged_count = len(disk_files) - len(new_files) - len(changed_files)

    logger.info(
        "  New: %d  |  Changed: %d  |  Unchanged: %d (skipped)  |  Deleted: %d",
        len(new_files), len(changed_files), unchanged_count, len(deleted_files)
    )

    # â”€â”€ Delete removed files from DB â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for fpath in deleted_files:
        logger.debug("Removing deleted file from DB: %s", fpath)
        db_delete_feature(conn, fpath)
    if deleted_files:
        logger.info("Removed %d deleted files from DB.", len(deleted_files))

    # â”€â”€ Delete changed files (will be re-inserted) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for fpath in changed_files:
        db_delete_feature(conn, fpath)

    # â”€â”€ Parse and insert new + changed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    to_parse = new_files + changed_files
    if not to_parse:
        logger.info("Nothing to parse â€” catalogue is up to date.")
    else:
        logger.info("Parsing %d file(s) ...", len(to_parse))
        n_ok    = 0
        n_error = 0
        n_scenarios = 0
        n_steps     = 0

        t0 = time.perf_counter()
        for i, fpath in enumerate(to_parse, 1):
            mtime = os.path.getmtime(fpath)
            parsed = parse_file(fpath)

            if parsed["parse_error"]:
                logger.warning("[%d/%d] PARSE ERROR %s â€” %s",
                               i, len(to_parse), os.path.basename(fpath), parsed["parse_error"])
                n_error += 1
                # Still insert the features row so we track the file
                try:
                    db_insert_feature(conn, {**parsed, "scenarios": []}, mtime)
                except Exception as exc:
                    logger.error("DB insert failed for %s: %s", fpath, exc)
                continue

            try:
                db_insert_feature(conn, parsed, mtime)
                n_ok       += 1
                n_scenarios += len(parsed["scenarios"])
                n_steps     += sum(len(sc["steps"]) for sc in parsed["scenarios"])
            except Exception as exc:
                logger.error("[%d/%d] DB INSERT FAILED %s â€” %s",
                             i, len(to_parse), os.path.basename(fpath), exc)
                n_error += 1

            if i % 100 == 0:
                elapsed = time.perf_counter() - t0
                logger.info(
                    "  Progress: %d/%d  (%.0fs elapsed)", i, len(to_parse), elapsed
                )

        elapsed = time.perf_counter() - t0
        logger.info(
            "Parsed %d file(s) in %.1fs  |  OK: %d  Errors: %d  "
            "Scenarios: +%d  Steps: +%d",
            len(to_parse), elapsed, n_ok, n_error, n_scenarios, n_steps
        )

    # â”€â”€ Refresh materialised view â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("Refreshing unique_steps materialised view ...")
    db_refresh_unique_steps(conn)

    # â”€â”€ Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    totals = db_total_counts(conn)
    logger.info(
        "Done. DB totals â€” Files: %d  Scenarios: %d  Steps: %d",
        totals["files"], totals["scenarios"], totals["steps"]
    )
    logger.info(
        "Next step: python tools/cli/build_index.py   (to rebuild vector index)"
    )

    release_conn(conn)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CLI entry point
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    parser = argparse.ArgumentParser(
        description="CASForge â€” ingest ATDD feature files into PostgreSQL"
    )
    parser.add_argument(
        "--full-rebuild", action="store_true",
        help="Drop + recreate schema, then re-parse all files"
    )
    args = parser.parse_args()

    if not FEATURES_REPO_PATH:
        logger.error(
            "FEATURES_REPO_PATH is not set in .env â€” "
            "add it and point it to your ATDD repo root."
        )
        sys.exit(1)

    run_ingest(FEATURES_REPO_PATH, full_rebuild=args.full_rebuild)


if __name__ == "__main__":
    main()





