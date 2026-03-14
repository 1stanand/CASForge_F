from pathlib import Path
import sys


_PROJECT_ROOT = Path(__file__).resolve().parent
_SRC_ROOT = _PROJECT_ROOT / "src"

if _SRC_ROOT.is_dir():
    src_text = str(_SRC_ROOT)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
