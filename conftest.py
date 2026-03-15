"""
conftest.py — pytest/unittest path bootstrap.

Adds src/ to sys.path so `casforge` is importable without installation.
Run tests from the project root:
    python -m unittest discover -s test -v
    pytest test/
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
