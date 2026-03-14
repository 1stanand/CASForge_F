from pathlib import Path
import sys


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"

for candidate in (_PROJECT_ROOT, _SRC_ROOT):
    text = str(candidate)
    if candidate.is_dir() and text not in sys.path:
        sys.path.insert(0, text)
