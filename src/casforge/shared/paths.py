from __future__ import annotations

from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
ASSETS_ROOT = PROJECT_ROOT / "assets"
CONFIG_DIR = PROJECT_ROOT / "config"
TOOLS_ROOT = PROJECT_ROOT / "tools"
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"
DOCS_ROOT = PROJECT_ROOT / "docs"
TEST_ROOT = PROJECT_ROOT / "test"

TEMPLATES_DIR = ASSETS_ROOT / "templates"
PROMPTS_DIR = ASSETS_ROOT / "prompts"
WORKFLOW_ASSETS_DIR = ASSETS_ROOT / "workflow"
GENERATION_ASSETS_DIR = CONFIG_DIR
ORDER_JSON_PATH = WORKFLOW_ASSETS_DIR / "order.json"

REFERENCE_REPO_ROOT = WORKSPACE_ROOT / "reference_repo"
FEATURES_REPO_DIR = REFERENCE_REPO_ROOT / "Features"
SAMPLES_DIR = WORKSPACE_ROOT / "samples"

GENERATED_ROOT = WORKSPACE_ROOT / "generated"
DEFAULT_OUTPUT_DIR = GENERATED_ROOT / "output"
DEFAULT_OUTPUT_FINAL_DIR = GENERATED_ROOT / "output_final"
DEFAULT_OUTPUT_ORDERED_DIR = GENERATED_ROOT / "output_ordered"
DEFAULT_OUTPUT_UNORDERED_DIR = GENERATED_ROOT / "output_unordered"

INDEX_DIR = WORKSPACE_ROOT / "index"
SCRATCH_DIR = WORKSPACE_ROOT / "scratch"

WEB_ROOT = SRC_ROOT / "casforge" / "web"
WEB_FRONTEND_DIR = WEB_ROOT / "frontend"

STORAGE_ROOT = SRC_ROOT / "casforge" / "storage"
SCHEMA_SQL_PATH = STORAGE_ROOT / "schema.sql"
CREATE_VIEWS_SQL_PATH = STORAGE_ROOT / "CreateViews.sql"


def resolve_user_path(path: str | Path, base: Optional[str | Path] = None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    anchor = Path(base).resolve() if base is not None else PROJECT_ROOT
    return (anchor / candidate).resolve()


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
