"""
scripts/validate_generated_features.py
-------------------------------------
Validate generated .feature files in output/:
  - starts with Feature:
  - scenarios use Scenario Outline
  - every scenario has Examples
  - every step text exists in repository steps table

Usage:
    python scripts/validate_generated_features.py
    python scripts/validate_generated_features.py --dir output
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from difflib import SequenceMatcher


from casforge.storage.connection import get_conn, release_conn, get_cursor
from casforge.shared.paths import resolve_user_path
from casforge.shared.settings import OUTPUT_DIR
from casforge.retrieval.retrieval import search

STEP_RE = re.compile(r"^\s*(Given|When|Then|And|But)\s+(.*\S)\s*$")
NEW_STEP_RE = re.compile(r"^\s*#\s*\[NEW_STEP_NOT_IN_REPO\]\s+(Given|When|Then|And|But)\s+(.*\S)\s*$")
_TEMPLATE_BOILERPLATE = {
    "all prerequisite are performed in previous scenario of \"<producttype>\" logical id \"<logicalid>\"",
    "user is on cas login page",
    "user logged in cas with valid username and password present in \"logindetailscas.xlsx\" under \"logindata\" and 0",
}


def _canonical(text: str) -> str:
    out = (text or "").strip().lower()
    out = re.sub(r"<[^>]+>", "<var>", out)
    return re.sub(r"\s+", " ", out)


def _step_exists(cur, step_text: str, cache: dict[str, bool]) -> bool:
    canonical = _canonical(step_text)
    if not canonical:
        return False
    if canonical in cache:
        return cache[canonical]
    if canonical in _TEMPLATE_BOILERPLATE:
        cache[canonical] = True
        return True

    cur.execute(
        """
        SELECT 1
        FROM steps
        WHERE regexp_replace(lower(trim(step_text)), '[[:space:]]+', ' ', 'g') = %s
           OR regexp_replace(lower(trim(split_part(step_text, E'\\n', 1))), '[[:space:]]+', ' ', 'g') = %s
           OR regexp_replace(
                regexp_replace(lower(trim(step_text)), '^(given|when|then|and|but)\\s+', '', 'i'),
                '[[:space:]]+', ' ', 'g'
              ) = %s
           OR regexp_replace(
                regexp_replace(lower(trim(split_part(step_text, E'\\n', 1))), '^(given|when|then|and|but)\\s+', '', 'i'),
                '[[:space:]]+', ' ', 'g'
              ) = %s
        LIMIT 1
        """,
        (canonical, canonical, canonical, canonical),
    )
    if cur.fetchone() is not None:
        cache[canonical] = True
        return True

    # Fuzzy fallback for placeholderized or whitespace-variant step forms.
    cur.execute(
        """
        SELECT
          GREATEST(
            word_similarity(regexp_replace(lower(trim(step_text)), '[[:space:]]+', ' ', 'g'), %s),
            word_similarity(regexp_replace(lower(trim(split_part(step_text, E'\\n', 1))), '[[:space:]]+', ' ', 'g'), %s),
            word_similarity(
                regexp_replace(
                    regexp_replace(lower(trim(step_text)), '^(given|when|then|and|but)\\s+', '', 'i'),
                    '[[:space:]]+', ' ', 'g'
                ),
                %s
            ),
            word_similarity(
                regexp_replace(
                    regexp_replace(lower(trim(split_part(step_text, E'\\n', 1))), '^(given|when|then|and|but)\\s+', '', 'i'),
                    '[[:space:]]+', ' ', 'g'
                ),
                %s
            )
          ) AS sim
        FROM steps
        WHERE lower(step_text) %% %s
           OR lower(split_part(step_text, E'\\n', 1)) %% %s
        ORDER BY sim DESC
        LIMIT 1
        """,
        (canonical, canonical, canonical, canonical, canonical, canonical),
    )
    row = cur.fetchone()
    sim = float(row["sim"]) if row and row.get("sim") is not None else 0.0
    ok = sim >= 0.72
    if not ok:
        hits = search(step_text, top_k=1)
        if hits:
            candidate = str(hits[0].get("step_text", "")).strip()
            candidate = re.sub(r"^(Given|When|Then|And|But)\s+", "", candidate, flags=re.IGNORECASE)
            cand_can = _canonical(candidate)
            if cand_can == canonical or SequenceMatcher(None, cand_can, canonical).ratio() >= 0.93:
                ok = True
    cache[canonical] = ok
    return ok


def _find_feature_index(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("Feature:"):
            return i
        if stripped.startswith("@") or stripped.startswith("#${"):
            continue
        return -1
    return -1


def _validate_file(path: str, cur) -> list[str]:
    errors: list[str] = []
    step_cache: dict[str, bool] = {}
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    allowed_new_steps = {
        _canonical(m.group(2).strip())
        for line in lines
        for m in [NEW_STEP_RE.match(line)]
        if m
    }

    feature_idx = _find_feature_index(lines)
    if feature_idx < 0:
        errors.append("missing Feature: header")
    else:
        for i, line in enumerate(lines[:feature_idx]):
            if line.lstrip().startswith("Scenario"):
                errors.append(f"line {i + 1}: Scenario appears before Feature header")
                break

    scenario_starts: list[int] = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("Scenario:"):
            errors.append(f"line {i + 1}: uses Scenario instead of Scenario Outline")
        if stripped.startswith("Scenario Outline:"):
            scenario_starts.append(i)

        m = STEP_RE.match(line)
        if m:
            step_text = m.group(2).strip()
            canonical = _canonical(step_text)
            if canonical in allowed_new_steps:
                continue
            if not _step_exists(cur, step_text, step_cache):
                errors.append(f"line {i + 1}: step not found in DB -> {m.group(2)}")

    for idx, start in enumerate(scenario_starts):
        end = scenario_starts[idx + 1] if idx + 1 < len(scenario_starts) else len(lines)
        block = lines[start:end]
        has_examples = any(x.strip().startswith("Examples:") for x in block)
        if not has_examples:
            errors.append(f"line {start + 1}: Scenario Outline missing Examples block")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=OUTPUT_DIR, help="Directory with generated .feature files")
    args = parser.parse_args()

    out_dir = str(resolve_user_path(args.dir))
    if not os.path.isdir(out_dir):
        print(f"Output directory not found: {out_dir}")
        return 1

    files = sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir)
        if f.lower().endswith(".feature")
    )
    if not files:
        print(f"No .feature files in {out_dir}")
        return 1

    conn = get_conn()
    total_errors = 0
    try:
        with get_cursor(conn) as cur:
            for path in files:
                errs = _validate_file(path, cur)
                if errs:
                    total_errors += len(errs)
                    print(f"[FAIL] {os.path.basename(path)}")
                    for e in errs:
                        print(f"  - {e}")
                else:
                    print(f"[OK]   {os.path.basename(path)}")
    finally:
        release_conn(conn)

    print(f"\nChecked {len(files)} file(s). Total issues: {total_errors}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())






