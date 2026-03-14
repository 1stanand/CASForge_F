"""
Single source of truth for all CASForge configuration.

All other modules import from here; nobody reads `os.getenv()` directly.
Values are loaded from the project-root `.env`, while default filesystem
locations come from the canonical repository layout in `casforge.shared.paths`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from casforge.shared import paths


load_dotenv(paths.PROJECT_ROOT / ".env", override=True)


DB_NAME = os.getenv("DATABASE_NAME", "CASForge_F")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))


_features_repo_env = os.getenv("FEATURES_REPO_PATH", "").strip()
FEATURES_REPO_PATH = _features_repo_env if _features_repo_env else str(paths.FEATURES_REPO_DIR)

_faiss_env = os.getenv("FAISS_INDEX_DIR", "").strip()
FAISS_INDEX_DIR = _faiss_env if _faiss_env else str(paths.INDEX_DIR)

SCHEMA_PATH = str(paths.SCHEMA_SQL_PATH)


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


LLM_MODEL_PATH = os.getenv("LLM_MODEL_PATH", "")
LLM_CONTEXT_LENGTH = int(os.getenv("LLM_CONTEXT_LENGTH", "4096"))
LLM_GPU_LAYERS = int(os.getenv("LLM_GPU_LAYERS", "0"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_NUM_THREADS = int(os.getenv("LLM_NUM_THREADS", "0"))


_output_env = os.getenv("OUTPUT_DIR", "").strip()
OUTPUT_DIR = _output_env if _output_env else str(paths.DEFAULT_OUTPUT_DIR)
