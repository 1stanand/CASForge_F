"""
smoke_intent_retrieval.py
--------------------------
Quick diagnostic:
  1. Parse one JIRA story
  2. Extract intents (1 LLM call)
  3. For intents 1 and 2: run retrieval only, print top scenario candidates
     (no forge LLM call — that would be slow)

Usage:
  python tools/cli/smoke_intent_retrieval.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from casforge.parsing.jira_parser import load_story
from casforge.generation.intent_extractor import extract_intents
from casforge.retrieval.retrieval import search

CSV  = "workspace/samples/sampleJira/committee.csv"
KEY  = "CAS-264757"
TOP_K = 8

# ── 1. Parse story ────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: Parse story")
print("=" * 70)
story = load_story(CSV, KEY)
print(f"  Key    : {story.issue_key}")
print(f"  Summary: {story.summary}")
sp = (story.system_process or "").strip()[:300]
print(f"  SysProc: {sp}...")
print()

# ── 2. Extract intents (one LLM call) ────────────────────────────────────────
print("=" * 70)
print("STEP 2: Extract intents (LLM)")
print("=" * 70)
intents = extract_intents(story)
print(f"  Extracted {len(intents)} intents\n")
for i, intent in enumerate(intents, 1):
    print(f"  [{i:02d}] [{intent.get('family','?'):20s}] {intent.get('text','')}")
print()

# ── 3. Retrieval check for intents 1 and 2 ───────────────────────────────────
check_count = min(2, len(intents))
for n in range(check_count):
    intent = intents[n]
    intent_text = intent.get("text", "")
    print("=" * 70)
    print(f"STEP 3.{n+1}: Retrieval for intent [{n+1}]")
    print(f"  Intent: {intent_text}")
    print(f"  Family: {intent.get('family', '?')}")
    print("-" * 70)

    results = search(query=intent_text, top_k=TOP_K)
    if not results:
        print("  !! No results returned")
        continue

    # Group into unique scenarios
    seen: dict = {}
    for r in results:
        key = (r.get("scenario_title") or "", r.get("file_name") or "")
        if key not in seen:
            seen[key] = r
        else:
            seen[key]["score"] = max(seen[key]["score"], r.get("score", 0))

    unique = sorted(seen.values(), key=lambda x: -x["score"])[:5]
    print(f"  Top {len(unique)} unique scenarios:\n")

    for i, scen in enumerate(unique, 1):
        print(f"  {i}. [{scen.get('file_name','')}]")
        print(f"     Title : {scen.get('scenario_title', '(untitled)')}")
        print(f"     Score : {scen.get('score', 0):.3f}")
        steps = scen.get("scenario_steps") or []
        for s in steps[:6]:
            kw   = s.get("keyword", "")
            text = s.get("step_text", "")
            print(f"       {kw} {text}")
        eb = scen.get("example_blocks") or []
        if eb:
            hdrs = eb[0].get("headers") or []
            rows = (eb[0].get("rows") or [])[:2]
            print(f"     Examples headers: {hdrs}")
            for row in rows:
                print(f"       {row}")
        print()
    print()
