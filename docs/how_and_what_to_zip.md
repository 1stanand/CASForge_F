# How and What to Zip — CASForge Transfer Package

## What to Include

```
CASForge_F/
  assets/          ← prompts, templates, workflow order.json
  casforge/        ← import stub (tiny, keep it)
  config/          ← domain_knowledge.json, planner_hints.json, assembler_hints.json
  docs/            ← all documentation
  src/             ← all Python source code
  test/            ← all unit tests
  tools/           ← CLI scripts + windows .bat files
  requirements.txt
  setup.py
  .env.example     ← if it exists; rename your .env to .env.example and blank out secrets
```

## What to EXCLUDE

```
workspace/reference_repo/   ← ATDD feature corpus (large, re-ingest on target machine)
workspace/samples/          ← sample JIRA CSVs (sensitive data)
workspace/generated/        ← generated .feature outputs
workspace/index/            ← FAISS index (rebuild with build_index.py)
workspace/                  ← the entire workspace/ folder

.env                        ← contains DB password and LLM path (DO NOT include)
.git/                       ← git history (optional — include if you want history)
__pycache__/                ← Python bytecode (auto-generated)
*.pyc                       ← Python bytecode
.pytest_cache/
```

---

## Option A — PowerShell (Windows, recommended)

Run from the **parent** folder of CASForge_F (e.g. `D:\`):

```powershell
$src  = "D:\CASForge_F"
$dest = "D:\CASForge_transfer.zip"

$exclude = @(
    "$src\workspace",
    "$src\.env",
    "$src\.git"
)

# Collect all items NOT in the exclude list
$items = Get-ChildItem -Path $src -Force |
    Where-Object { $_.FullName -notin $exclude }

Compress-Archive -Path $items -DestinationPath $dest -Force
Write-Host "Created: $dest"
```

> **Note:** This does NOT recurse into excluded folders. Any nested `__pycache__` inside
> `src/` or `test/` will still be included — they are harmless (Python ignores stale .pyc).
> To strip them too, use the Python method below.

---

## Option B — Python (cross-platform, cleanest)

Run from the **project root** `D:\CASForge_F`:

```powershell
python tools/cli/create_transfer_zip.py
```

This script (provided below) correctly excludes `workspace/`, `.env`, `.git/`,
and all `__pycache__` folders.

**Script to save as `tools/cli/create_transfer_zip.py`:**

```python
"""
Create a clean transfer zip of CASForge_F, excluding workspace/, .env, .git/, __pycache__.
Run from the project root: python tools/cli/create_transfer_zip.py
"""
import zipfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # d:\CASForge_F
OUT  = ROOT.parent / "CASForge_transfer.zip"

EXCLUDE_DIRS  = {"workspace", ".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_FILES = {".env"}
EXCLUDE_EXTS  = {".pyc", ".pyo"}

count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in ROOT.rglob("*"):
        # Skip excluded dirs (check any part of the path)
        parts = set(path.parts)
        if parts & EXCLUDE_DIRS:
            continue
        # Skip excluded filenames and extensions
        if path.name in EXCLUDE_FILES:
            continue
        if path.suffix in EXCLUDE_EXTS:
            continue
        if path.is_file():
            arcname = path.relative_to(ROOT.parent)   # preserve CASForge_F/ prefix
            zf.write(path, arcname)
            count += 1

print(f"Created: {OUT}")
print(f"Files included: {count}")
```

---

## Option C — 7-Zip (GUI, if you prefer)

1. Right-click `CASForge_F` folder → **7-Zip → Add to archive**
2. Archive name: `CASForge_transfer.zip`
3. After creating, **open the zip** and manually delete:
   - `CASForge_F\workspace\`
   - `CASForge_F\.env`
   - `CASForge_F\.git\`

---

## After Transfer — First-Time Setup on New Machine

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env with your DB credentials and LLM path
#    (copy .env.example and fill in values)

# 3. Setup DB + ingest corpus + build index
python setup.py

# 4. Start server
tools\windows\start_server.bat
```

Full instructions: see `docs/HOW_TO_RUN.md`
