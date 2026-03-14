"""
scripts/build_index.py
----------------------
Reads all unique step texts from the DB (unique_steps materialised view)
and builds / rebuilds the FAISS vector index on disk.

Run after ingest.py whenever new files have been added:
    python scripts/build_index.py

Must be run from the project root:
    cd D:\\CAS_FORGE_FINAL
    python scripts/build_index.py
"""

import logging
import os
import sys

from casforge.storage.connection import get_conn, get_cursor
from casforge.retrieval.embedder import build_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    conn = get_conn()
    try:
        with get_cursor(conn) as cur:
            logger.info("Loading unique steps from DB ...")
            cur.execute("SELECT id, step_text FROM unique_steps ORDER BY id")
            rows = cur.fetchall()
        logger.info("Loaded %d unique steps.", len(rows))
    finally:
        conn.close()

    if not rows:
        logger.error("No steps found in DB. Run ingest.py first.")
        sys.exit(1)

    # rows is a list of RealDictRow â€” build_index expects list[{id, step_text}]
    build_index([{"id": r["id"], "step_text": r["step_text"]} for r in rows])
    logger.info("Index build complete.")


if __name__ == "__main__":
    main()


