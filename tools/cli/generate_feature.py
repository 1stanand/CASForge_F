"""
scripts/generate_feature.py
---------------------------
Phase 2 CLI: JIRA story â†’ Gherkin .feature file.

Pipeline
--------
    JIRA CSV  â†’  parse story fields
              â†’  Llama: extract testable intents
              â†’  CASForge retrieval: find matching steps per intent
              â†’  Llama: assemble .feature file from intents + step candidates
              â†’  write .feature file to output/

Usage
-----
    # Generate for a single story (requires --csv to locate the story)
    python scripts/generate_feature.py --csv SampleJira/sampleJira/HD_Bank_Epic.csv --story CAS-256008

    # Generate for all stories in a CSV
    python scripts/generate_feature.py --csv SampleJira/sampleJira/HD_Bank_Epic.csv --all

    # Dry-run: show extracted intents without calling the assembler
    python scripts/generate_feature.py --csv ... --story CAS-256008 --intents-only

    # Override output directory
    python scripts/generate_feature.py --csv ... --story CAS-256008 --output D:\\MyOutput
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Imports (after sys.path fix)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

from casforge.parsing.jira_parser import load_story, load_all_stories
from casforge.generation.intent_extractor import extract_intents, infer_story_scope_defaults
from casforge.generation.feature_assembler import assemble_feature_result
from casforge.shared.paths import resolve_user_path
from casforge.shared.settings import OUTPUT_DIR


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Core generation logic
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def generate(
    csv_path: str,
    story_key: str,
    output_dir: str,
    flow_type: str | None,
    intents_only: bool = False,
) -> str | None:
    """
    Generate a .feature file for one JIRA story.

    Returns the path of the written file, or None if intents_only=True.
    """
    print(f"\n{'='*60}")
    print(f"  Story: {story_key}")
    print(f"{'='*60}")

    # 1. Parse JIRA story
    print("  [1/3] Parsing JIRA story...")
    story = load_story(csv_path, story_key)
    print(f"        Title   : {story.summary}")
    print(f"        Type    : {story.issue_type}")
    print(f"        Stage(s): {story.impacted_areas[:80] if story.impacted_areas else 'â€”'}")
    defaults = infer_story_scope_defaults(story)
    lob_scope = defaults.get("lob_scope", {})
    stage_scope = defaults.get("stage_scope", {})
    if lob_scope.get("mode") == "specific" and lob_scope.get("values"):
        print(f"        LOB Scope (inferred): {', ' .join(lob_scope['values'])}")
    if stage_scope.get("mode") == "specific" and stage_scope.get("values"):
        print(f"        Stage Scope (inferred): {', ' .join(stage_scope['values'])}")

    # 2. Extract intents
    print("  [2/3] Extracting test intents via LLM...")
    intents = extract_intents(story, story_scope_defaults=defaults)
    if not intents:
        print("  ERROR: LLM returned no intents â€” check model output.")
        return None

    print(f"        {len(intents)} intents extracted:")
    for i, intent in enumerate(intents, 1):
        text = intent.get("text", "") if isinstance(intent, dict) else str(intent)
        family = intent.get("family", "positive") if isinstance(intent, dict) else "positive"
        print(f"          {i}. [{family}] {text}")

    if intents_only:
        return None

    # 3. Assemble feature file
    print("  [3/3] Assembling .feature file via LLM (+ retrieval)...")
    if flow_type not in {"ordered", "unordered"}:
        raise ValueError("flow_type must be explicitly set to 'ordered' or 'unordered'")
    result = assemble_feature_result(story, intents, flow_type=flow_type, story_scope_defaults=defaults)
    feature_text = result.feature_text

    # 4. Write to disk
    os.makedirs(output_dir, exist_ok=True)
    safe_key = story_key.replace("-", "_")
    out_path = os.path.join(output_dir, f"{safe_key}.feature")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(feature_text)
        f.write("\n")

    print(f"\n  Written: {out_path}")
    print(f"  Quality : {result.quality}")
    if result.unresolved_steps:
        print(f"  Unresolved steps: {len(result.unresolved_steps)}")
        for s in result.unresolved_steps[:5]:
            print(f"    - [{s.get('keyword','?')}] {s.get('step_text','')}")
    print()
    print(feature_text)
    print()

    return out_path


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CLI
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_args():
    p = argparse.ArgumentParser(
        description="CASForge Phase 2 â€” generate Gherkin .feature files from JIRA stories"
    )
    p.add_argument(
        "--csv", required=True,
        help="Path to JIRA CSV export file",
    )
    p.add_argument(
        "--story", default=None,
        help="JIRA issue key to process (e.g. CAS-256008)",
    )
    p.add_argument(
        "--all", action="store_true",
        help="Process all stories in the CSV",
    )
    p.add_argument(
        "--flow-type",
        choices=("ordered", "unordered"),
        default=None,
        help="Mandatory for feature generation: choose ordered or unordered flow",
    )
    p.add_argument(
        "--output", default=None,
        help=f"Output directory for .feature files (default: {OUTPUT_DIR})",
    )
    p.add_argument(
        "--intents-only", action="store_true",
        help="Only extract and print intents â€” skip feature file assembly",
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
                result = generate(csv_path, s.issue_key, output_dir, args.flow_type, args.intents_only)
                if result or args.intents_only:
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





