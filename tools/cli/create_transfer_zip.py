"""
Create a clean transfer zip of CASForge_F, excluding workspace/, .env, .git/, __pycache__.
Run from the project root: python tools/cli/create_transfer_zip.py
Output: D:\CASForge_transfer.zip  (next to the project folder)
"""
import zipfile
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # d:\CASForge_F
OUT  = ROOT.parent / "CASForge_transfer.zip"

EXCLUDE_DIRS  = {"workspace", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
                  ".VSCodeCounter", ".claude", "agent"}
EXCLUDE_FILES = {".env"}
EXCLUDE_EXTS  = {".pyc", ".pyo"}
# Stray generated files in the project root
EXCLUDE_NAMES_ROOT = {".env.example"}  # not a root exclude, but root-level .feature files


print(f"Zipping: {ROOT}")
print(f"Output : {OUT}")
print("Excluding: workspace/, .git/, __pycache__, .env, *.pyc")
print()

count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(ROOT.rglob("*")):
        # Skip excluded dirs (check any part of the relative path)
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        # Skip excluded filenames and extensions
        if path.name in EXCLUDE_FILES:
            continue
        if path.suffix in EXCLUDE_EXTS:
            continue
        if path.is_file():
            # Skip stray .feature files directly in the project root
            if path.parent == ROOT and path.suffix == ".feature":
                continue
            arcname = path.relative_to(ROOT.parent)   # keeps CASForge_F/ prefix
            zf.write(path, arcname)
            count += 1
            if count % 50 == 0:
                print(f"  {count} files...")

print(f"\nDone. {count} files -> {OUT}")
print(f"Size : {OUT.stat().st_size / 1024:.0f} KB")
