"""
tools/cli/generate_feature.py
------------------------------
CLI: JIRA story → Gherkin .feature file via forge_feature().

Pipeline
--------
    JIRA CSV  →  parse story fields
              →  LLM: extract testable intents
              →  forge_feature: retrieval + LLM scenario pick/prune per intent
              →  write .feature file to output/

Usage
-----
    # Single story
    python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv \
        --story CAS-256008 --flow-type unordered

    # All stories in a CSV
    python tools/cli/generate_feature.py --csv workspace/samples/sampleJira/HD_BANK_EPIC.csv \
        --all --flow-type ordered

    # Intents only (no feature file, no forge LLM)
    python tools/cli/generate_feature.py --csv ... --story CAS-256008 --intents-only

    # Custom output directory
    python tools/cli/generate_feature.py --csv ... --story CAS-256008 \
        --flow-type ordered --output workspace/generated/custom
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(name)s  %(message)s",
)
_log = logging.getLogger("generate_feature")


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from casforge.parsing.jira_parser import load_story, load_all_stories
from casforge.generation.intent_extractor import extract_intents, infer_story_scope_defaults
from casforge.generation.forge import forge_feature
from casforge.shared.paths import resolve_user_path
from casforge.shared.settings import OUTPUT_DIR


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def generate(
    csv_path: str,
    story_key: str,
    output_dir: str,
    flow_type: str | None,
    intents_only: bool = False,
) -> str | None:
    """
    Generate a .feature file for one JIRA story.
    Returns the path of the written file, or None if intents_only=True or error.
    """
    sep = "-" * 60
    print(f"\n{'='*60}")
    print(f"  Story: {story_key}")
    print(f"{'='*60}")

    # 1. Parse JIRA story
    print("  [1/3] Parsing JIRA story...")
    story = load_story(csv_path, story_key)
    print(f"        Title   : {story.summary}")
    print(f"        Type    : {story.issue_type}")
    print(f"        Stage(s): {story.impacted_areas[:80] if story.impacted_areas else '—'}")

    # 2. Extract intents via LLM
    print("  [2/3] Extracting test intents via LLM...")
    defaults = infer_story_scope_defaults(story)
    intents = extract_intents(story, story_scope_defaults=defaults)
    if not intents:
        print("  ERROR: LLM returned no intents — check model output.")
        return None

    print(f"        {len(intents)} intents extracted:")
    for i, intent in enumerate(intents, 1):
        text   = intent.get("text", "")   if isinstance(intent, dict) else str(intent)
        family = intent.get("family", "") if isinstance(intent, dict) else ""
        print(f"          {i:2d}. [{family}] {text}")

    if intents_only:
        return None

    # 3. Forge feature file (retrieval + LLM per intent)
    print("  [3/3] Forging .feature file (retrieval + LLM)...")
    if flow_type not in {"ordered", "unordered"}:
        raise ValueError("flow_type must be 'ordered' or 'unordered'")

    result = forge_feature(
        story,
        intents,
        flow_type=flow_type,
        on_progress=lambda msg: print(f"        {msg}"),
    )

    # 4. Write to disk
    os.makedirs(output_dir, exist_ok=True)
    safe_key = story_key.replace("-", "_")
    out_path = os.path.join(output_dir, f"{safe_key}.feature")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result.feature_text)
        if not result.feature_text.endswith("\n"):
            f.write("\n")

    print(f"\n  Written : {out_path}")
    print(f"  Quality : {result.quality}")

    total_steps = result.quality.get("total_steps", 0)
    grounded    = result.quality.get("grounded_steps", 0)
    unresolved  = result.quality.get("unresolved_steps", 0)
    omitted     = len(result.omitted_plan_items)
    scenarios   = result.quality.get("scenario_count", 0)

    print(f"  Scenarios      : {scenarios}")
    print(f"  Total steps    : {total_steps}")
    print(f"  Grounded steps : {grounded}  ({grounded*100//total_steps if total_steps else 0}%)")
    print(f"  New/ungrounded : {unresolved}  ({unresolved*100//total_steps if total_steps else 0}%)")
    print(f"  Omitted intents: {omitted}")
    if result.omitted_plan_items:
        for o in result.omitted_plan_items[:5]:
            reason = o.get("reason", "") if isinstance(o, dict) else str(o)
            text   = o.get("text", "")   if isinstance(o, dict) else ""
            print(f"    - {text[:60]}  [{reason}]")

    print(f"\n{sep}")
    # Print feature text safely (Windows console may not support all Unicode)
    try:
        print(result.feature_text)
    except UnicodeEncodeError:
        print(result.feature_text.encode("ascii", errors="replace").decode("ascii"))
    print(f"{sep}\n")

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(
        description="CASForge — generate Gherkin .feature files from JIRA stories"
    )
    p.add_argument("--csv",   required=True,  help="Path to JIRA CSV file")
    p.add_argument("--story", default=None,   help="JIRA issue key (e.g. CAS-256008)")
    p.add_argument("--all",   action="store_true", help="Process all stories in the CSV")
    p.add_argument(
        "--flow-type", choices=("ordered", "unordered"), default=None,
        help="Flow type for feature generation",
    )
    p.add_argument(
        "--output", default=None,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    p.add_argument(
        "--intents-only", action="store_true",
        help="Only extract and print intents — skip feature assembly",
    )
    return p.parse_args()


def main():
    args = _parse_args()

    if not args.story and not args.all:
        print("ERROR: specify --story <key> or --all")
        sys.exit(1)

    if not args.intents_only and not args.flow_type:
        print("ERROR: --flow-type is mandatory for generation (ordered|unordered).")
        sys.exit(1)

    csv_path   = str(resolve_user_path(args.csv))
    output_dir = str(resolve_user_path(args.output)) if args.output else OUTPUT_DIR

    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    if args.all:
        stories = load_all_stories(csv_path)
        print(f"Found {len(stories)} stories in {csv_path}")
        success = 0
        for s in stories:
            try:
                r = generate(csv_path, s.issue_key, output_dir, args.flow_type, args.intents_only)
                if r or args.intents_only:
                    success += 1
            except Exception as exc:
                _log.error("Failed for %s: %s", s.issue_key, exc, exc_info=True)
        print(f"\nDone. {success}/{len(stories)} succeeded.")
    else:
        try:
            generate(csv_path, args.story, output_dir, args.flow_type, args.intents_only)
        except Exception as exc:
            _log.error("Failed: %s", exc, exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
