"""
tools/cli/smoke_small_chunks.py
-------------------------------
Fast component-level smoke checks before expensive full JIRA -> feature runs.
"""

from __future__ import annotations

import argparse
import re

from casforge.generation.feature_assembler import assemble_feature, assemble_feature_result
from casforge.generation.scenario_planner import build_scenario_plan_items
from casforge.generation.story_facts import infer_story_facts_heuristically
from casforge.parsing.jira_parser import load_story
from casforge.shared.paths import TEST_ROOT

TINY_CLEAN = str(TEST_ROOT / 'resources' / 'test-specs' / 'tiny_clean.csv')
TINY_MESSY = str(TEST_ROOT / 'resources' / 'test-specs' / 'tiny_messy.csv')


def _ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _check_parser_cleanup() -> tuple[bool, str]:
    story = load_story(TINY_MESSY, "TINY-2")
    text = " ".join([
        story.description,
        story.new_process,
        story.business_scenarios,
        story.acceptance_criteria,
        story.story_description,
    ]).lower()
    blocked = ("{color", "{code", "http://")
    leaks = [b for b in blocked if b in text]
    if leaks:
        return False, f"markup leaks found in parsed text: {leaks}"
    return True, "messy jira parsed and cleaned"


def _check_story_facts() -> tuple[bool, str]:
    story = load_story(TINY_CLEAN, "TINY-1")
    facts = infer_story_facts_heuristically(story)
    if not facts.get("rules"):
        return False, "story facts extraction returned no rules"
    if not facts.get("coverage_signals"):
        return False, "story facts extraction returned no coverage signals"
    return True, f"story facts passed (rules={len(facts['rules'])}, coverage={','.join(facts['coverage_signals'])})"


def _check_planner() -> tuple[bool, str]:
    story = load_story(TINY_CLEAN, "TINY-1")
    facts = infer_story_facts_heuristically(story)
    plan_items = build_scenario_plan_items(story, story_facts=facts)
    if len(plan_items) < 3:
        return False, f"expected at least 3 plan items, got {len(plan_items)}"
    if any(item['text'].lower().startswith('user logs in') for item in plan_items):
        return False, "planner produced setup-only intent"
    if not any(item['family'] in {'negative', 'validation', 'dependency'} for item in plan_items):
        return False, "planner missed non-core coverage families"
    if any(len(item['text'].split()) > 14 for item in plan_items):
        return False, "planner produced overlong intent text"
    return True, f"planner passed ({len(plan_items)} items)"


def _extract_intents_llm() -> tuple[bool, list[dict], str]:
    from casforge.generation.intent_extractor import extract_intents

    story = load_story(TINY_CLEAN, "TINY-1")
    intents = extract_intents(story)
    if len(intents) < 3:
        return False, intents, f"expected at least 3 intents, got {len(intents)}"
    if any(intent['text'].lower().startswith('user logs in') for intent in intents):
        return False, intents, "LLM-backed planner produced setup-only intent"
    if not any(intent['family'] in {'negative', 'validation', 'dependency'} for intent in intents):
        return False, intents, "LLM-backed planner missed non-core families"
    return True, intents, f"intent planning sanity passed ({len(intents)})"


def _default_intents() -> list[dict]:
    return [
        {
            "id": "intent_001",
            "text": "Finalize committee verdict when majority is reached",
            "family": "positive",
            "action_target": "committee verdict",
            "screen_hint": "Committee Approval",
            "expected_outcome": "derived_value",
            "entity": "committee verdict",
            "target_field": "committee verdict",
            "expected_state": "derived",
            "polarity": "positive",
            "must_anchor_terms": ["committee verdict", "majority"],
            "must_assert_terms": ["verdict", "majority"],
            "forbidden_terms": ["login", "property viewer"],
            "matrix_signature": "base",
            "allow_expansion": False,
        },
        {
            "id": "intent_002",
            "text": "Keep verdict pending when no majority is reached",
            "family": "negative",
            "action_target": "committee verdict",
            "screen_hint": "Committee Approval",
            "expected_outcome": "display",
            "entity": "committee verdict",
            "target_field": "committee verdict",
            "expected_state": "display",
            "polarity": "negative",
            "must_anchor_terms": ["committee verdict", "majority"],
            "must_assert_terms": ["pending", "mixed"],
            "forbidden_terms": ["approved"],
            "matrix_signature": "none",
            "allow_expansion": True,
        },
        {
            "id": "intent_003",
            "text": "Reject duplicate vote updates from same member",
            "family": "validation",
            "action_target": "duplicate vote update",
            "screen_hint": "Committee Approval",
            "expected_outcome": "validation_error",
            "entity": "committee verdict",
            "target_field": "vote update",
            "expected_state": "validation_error",
            "polarity": "negative",
            "must_anchor_terms": ["duplicate vote", "same member"],
            "must_assert_terms": ["reject", "error"],
            "forbidden_terms": ["saved"],
            "matrix_signature": "base",
            "allow_expansion": False,
        },
    ]


def _count_scenarios(feature_text: str) -> int:
    return sum(1 for ln in feature_text.splitlines() if ln.lstrip().startswith("Scenario Outline:"))


def _check_assertion_rule(feature_text: str) -> tuple[bool, str]:
    lines = feature_text.splitlines()
    scenario_starts = [i for i, ln in enumerate(lines) if ln.lstrip().startswith("Scenario Outline:")]
    for i, start in enumerate(scenario_starts):
        end = scenario_starts[i + 1] if i + 1 < len(scenario_starts) else len(lines)
        block = lines[start:end]
        then_idx = [j for j, ln in enumerate(block) if re.match(r"^\s*Then\s+", ln)]
        if not then_idx:
            return False, f"scenario at line {start + 1} has no Then"
        j = then_idx[0] + 1
        and_after_then = 0
        while j < len(block) and re.match(r"^\s*And\s+", block[j]):
            and_after_then += 1
            j += 1
        if and_after_then > 1:
            return False, f"scenario at line {start + 1} has {and_after_then} And steps after Then"
    return True, "assertion rule passed"


def _check_assembled_feature(flow_type: str, intents: list[dict]) -> tuple[bool, str]:
    story = load_story(TINY_CLEAN, "TINY-1")
    result = assemble_feature_result(story, intents[:3], flow_type=flow_type)
    feature = result.feature_text

    if "Feature:" not in feature:
        return False, f"{flow_type}: missing Feature header"
    if "Scenario Outline:" not in feature:
        return False, f"{flow_type}: missing Scenario Outline"

    sc_count = _count_scenarios(feature)
    coverage_gaps = int(result.quality.get('coverage_gaps', 0))
    if sc_count < 1:
        return False, f"{flow_type}: expected at least 1 scenario, got {sc_count}"
    if sc_count + coverage_gaps < 2:
        return False, f"{flow_type}: coverage too narrow (scenarios={sc_count}, gaps={coverage_gaps})"

    ok, msg = _check_assertion_rule(feature)
    if not ok:
        return False, f"{flow_type}: {msg}"

    marker_note = "with NEW_STEP_NOT_IN_REPO notice" if "NEW_STEP_NOT_IN_REPO" in feature else "all steps grounded"
    return True, f"{flow_type}: {sc_count} scenarios, gaps={coverage_gaps}, {msg}, {marker_note}"


def _check_section_headers() -> tuple[bool, str]:
    story = load_story(TINY_CLEAN, "TINY-1")
    result = assemble_feature_result(story, _default_intents(), flow_type="unordered")
    feature = result.feature_text
    has_section = any(
        marker in feature
        for marker in (
            "###### Core Flow Coverage",
            "###### Validation Coverage",
            "###### Negative Coverage",
            "###### UI Structure Validation",
            "###### Checkbox Availability & Default State",
            "###### Field Enablement Behaviour",
            "###### Decision Logic Behaviour",
            "###### Move To Next Stage Validations",
        )
    )
    if not has_section:
        return False, "section headers missing for family-grouped rendering"
    return True, f"section header rendering passed (scenarios={result.quality.get('scenario_count', 0)}, gaps={result.quality.get('coverage_gaps', 0)})"


def _check_scope_leak() -> tuple[bool, str]:
    story = load_story(TINY_CLEAN, "TINY-1")
    defaults = {
        "lob_scope": {"mode": "specific", "values": ["OMNI"]},
        "stage_scope": {"mode": "specific", "values": ["Recommendation"]},
    }
    result = assemble_feature_result(story, _default_intents()[:2], flow_type="unordered", story_scope_defaults=defaults)
    text = result.feature_text.lower()
    if "@creditapproval" in text and "@recommendation" not in text:
        return False, "scope leak detected: credit-approval tag present without recommendation context"
    return True, "scope leak gate passed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-llm", action="store_true", help="Also run tiny LLM-backed story-facts and intent planning check")
    args = parser.parse_args()

    failures = 0

    for check in (_check_parser_cleanup, _check_story_facts, _check_planner):
        ok, msg = check()
        if ok:
            _ok(msg)
        else:
            failures += 1
            _fail(msg)

    intents = _default_intents()
    if args.with_llm:
        ok, llm_intents, msg = _extract_intents_llm()
        if ok:
            _ok(msg)
            intents = llm_intents
        else:
            failures += 1
            _fail(msg)

    for flow in ("unordered", "ordered"):
        ok, msg = _check_assembled_feature(flow, intents)
        if ok:
            _ok(msg)
        else:
            failures += 1
            _fail(msg)

    for check in (_check_section_headers, _check_scope_leak):
        ok, msg = check()
        if ok:
            _ok(msg)
        else:
            failures += 1
            _fail(msg)

    print(f"\nSmall-chunk smoke result: {'PASS' if failures == 0 else 'FAIL'} (failures={failures})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
