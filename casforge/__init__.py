from pathlib import Path

# Redirect this stub package to the real implementation in src/casforge/.
# This allows `import casforge` to work when Python is run from the project root
# without requiring PYTHONPATH=src or a package installation.
__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "casforge")]
