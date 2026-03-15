"""
llm/intent_extractor.py
-----------------------
Scope-aware intent planning for CASForge.

Primary output is a structured list of intent objects:
  {
    "id": "intent_001",
    "text": "...",
    "family": "validation",
    "inherit_story_scope": true,
    "lob_scope": null,
    "stage_scope": null
  }

This module remains backward-compatible with legacy list[str] intent callers
via coerce_intents() and intents_to_legacy_texts().
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

from casforge.parsing.jira_parser import JiraStory
from casforge.generation import llm_client
from casforge.generation.heuristic_config import load_domain_knowledge
from casforge.generation.scenario_planner import build_scenario_plan_items, public_intent_records
from casforge.generation.story_facts import extract_story_facts
from casforge.shared.paths import PROMPTS_DIR
from casforge.shared.settings import LLM_TEMPERATURE, LLM_MAX_TOKENS
from casforge.workflow.ordering import detect_stage

_log = logging.getLogger(__name__)

_PROMPT_FILE = PROMPTS_DIR / "extract_intents.txt"

_MIN_INTENTS_TARGET = 8
_MAX_INTENTS_TARGET = 14

_FAMILY_ALIASES = {
    "core": "positive",
    "positive": "positive",
    "happy_path": "positive",
    "negative": "negative",
    "rejection": "negative",
    "validation": "validation",
    "mandatory": "validation",
    "dependency": "dependency",
    "dependent": "dependency",
    "state": "state_movement",
    "state_transition": "state_movement",
    "state_movement": "state_movement",
    "movement": "state_movement",
    "persistence": "persistence",
    "save": "persistence",
    "data_combination": "data_combination",
    "combination": "data_combination",
    "boundary": "data_combination",
    "edge": "edge",
}

_VALID_FAMILIES = {
    "positive",
    "negative",
    "validation",
    "dependency",
    "state_movement",
    "persistence",
    "data_combination",
    "edge",
}

_INTENT_FILLER = {
    "the", "a", "an", "user", "users", "should", "be", "able", "to", "system",
    "screen", "page", "that", "this", "for", "of", "and", "or", "in", "on",
    "at", "with", "as", "is", "are", "can",
}

_GENERIC_PATTERNS = (
    "system should work",
    "system should function",
    "works correctly",
    "as expected",
)

_NEGATIVE_HINTS = {"reject", "rejection", "error", "invalid", "not allow", "prevent", "fail", "failed"}
_VALIDATION_HINTS = {"mandatory", "required", "validation", "validate", "field", "enable", "disable"}
_DEPENDENCY_HINTS = {"depend", "linked", "sync", "propagate", "based on", "derived from"}
_STATE_HINTS = {"move to next", "stage", "transition", "state"}
_PERSIST_HINTS = {"save", "reopen", "persist", "retained", "retains"}
_DATA_HINTS = {"combination", "boundary", "minimum", "maximum", "range", "multiple", "matrix"}
_EDGE_HINTS = {"edge", "blank", "null", "zero", "duplicate"}

_OUTCOME_HINT_MAP = (
    ("validation_error", {"mandatory", "required", "validation", "invalid", "error"}),
    ("disabled", {"disable", "disabled", "read-only", "readonly", "noneditable"}),
    ("enabled", {"enable", "enabled", "editable"}),
    ("checked", {"checked", "checkbox", "selected"}),
    ("display", {"display", "visible", "show", "shown"}),
    ("rejection", {"reject", "rejected", "prevent", "blocked"}),
    ("save_success", {"save", "saved", "submit", "submitted", "update", "updated"}),
    ("derived_value", {"derive", "derived", "calculate", "calculated"}),
    ("persistence", {"persist", "retained", "retain", "reopen"}),
    ("state_change", {"move", "transition", "stage", "next"}),
)

_INTENT_VERBS = {
    "display", "show", "validate", "reject", "prevent", "save", "update",
    "derive", "calculate", "enable", "disable", "move", "retain", "persist",
    "remove", "add", "select", "submit", "approve", "reject", "capture",
}

def _lob_scope_hints() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return (canonical, phrases) pairs from domain_knowledge.json lob_aliases."""
    lob_aliases = load_domain_knowledge().get("lob_aliases") or {}
    return tuple((canonical, phrases) for canonical, phrases in lob_aliases.items())


def _load_prompt() -> tuple[str, str]:
    """Return (system_prompt, user_template) from the prompt file."""
    with open(_PROMPT_FILE, encoding="utf-8") as f:
        content = f.read()
    parts = content.split("\nUSER:\n", 1)
    if len(parts) != 2:
        raise ValueError(f"Prompt file {_PROMPT_FILE} must contain a 'USER:' section")
    system = parts[0].replace("SYSTEM:\n", "", 1).strip()
    user_template = parts[1].strip()
    return system, user_template


def _call_extract_intents_llm(
    story: JiraStory,
    defaults: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Call the LLM with extract_intents.txt to get direct one-liner test-case intents.

    The prompt asks for 8-12 intents in plain test-case language (6-14 words each)
    with optional planning hints (action_target, screen_hint, polarity, etc.).
    This is the preferred path: LLM thinks in test cases, not structured business rules.
    """
    try:
        system_prompt, user_template = _load_prompt()

        def _blk(header: str, text: str, limit: int) -> str:
            t = (text or "").strip()[:limit]
            return f"{header}:\n{t}\n\n" if t else ""

        scope_lines = []
        for scope_key, label in (("lob_scope", "LOB"), ("stage_scope", "Stage")):
            sc = defaults.get(scope_key, {})
            if sc.get("mode") == "specific" and sc.get("values"):
                scope_lines.append(f"{label}: {', '.join(sc['values'])}")
        scope_block = (
            "Story Scope Defaults:\n" + "\n".join(f"- {ln}" for ln in scope_lines) + "\n\n"
            if scope_lines else ""
        )

        user_prompt = user_template.format(
            key=story.issue_key,
            summary=story.summary,
            description=(story.description or story.story_description or "").strip()[:1200],
            new_process_block=_blk("New Behavior to Implement", story.new_process, 1600),
            business_scenarios_block=_blk("Business Scenarios / Exceptions", story.business_scenarios, 900),
            impacted_areas_block=_blk("Impacted CAS Areas / Stages", story.impacted_areas, 500),
            key_ui_block=_blk("Key UI Navigation", story.key_ui_steps, 500),
            acceptance_criteria_block=_blk("Acceptance Criteria", story.acceptance_criteria, 900),
            story_scope_block=scope_block,
        )
        raw = llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=min(LLM_TEMPERATURE, 0.15),
            max_tokens=max(640, min(LLM_MAX_TOKENS, 1400)),
        )
        records = _parse_intent_records(raw)
        return _dedupe_records(_normalise_records(records))
    except Exception as exc:
        _log.warning("Direct intent LLM extraction failed for %s: %s", story.issue_key, exc)
        return []


def extract_intents(
    story: JiraStory,
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Extract concise, structured intents using the extract_intents.txt prompt.

    The LLM is asked directly for test-case-style one-liner intents (6-14 words,
    one behavior each) with optional planning hints. This is cleaner than going
    through story_facts → deterministic planning.

    Flow:
      1. LLM direct extraction via extract_intents.txt
      2. If too few intents, augment with a coverage expansion pass
      3. Enrich with section_key / pattern_terms via scenario planner
      4. Fallback to old story_facts path only if everything above produces nothing
    """
    defaults = normalise_story_scope_defaults(story_scope_defaults)
    inferred = infer_story_scope_defaults(story)
    for key in ("lob_scope", "stage_scope"):
        if defaults.get(key, {}).get("mode") != "specific" and inferred.get(key, {}).get("mode") == "specific":
            defaults[key] = inferred[key]

    # Step 1: direct LLM intent extraction
    llm_intents = _call_extract_intents_llm(story, defaults)

    # Step 2: augment if thin
    if len(llm_intents) < _MIN_INTENTS_TARGET:
        extra = _expand_intents_for_coverage(story, llm_intents)
        llm_intents = _dedupe_records(llm_intents + extra)

    # Step 3: enrich with section_key, pattern_terms via planner (intents= path)
    planned = build_scenario_plan_items(
        story=story,
        story_scope_defaults=defaults,
        story_facts=None,
        intents=llm_intents or None,
    )

    # Step 4: fallback to old story_facts path if nothing produced
    if not planned:
        _log.warning(
            "Direct intent extraction produced nothing for %s — falling back to story_facts path",
            story.issue_key,
        )
        facts = extract_story_facts(story, story_scope_defaults=defaults)
        planned = build_scenario_plan_items(
            story=story,
            story_scope_defaults=defaults,
            story_facts=facts,
            intents=None,
        )

    intents = public_intent_records(planned)[:_MAX_INTENTS_TARGET]
    _log.info("Planned %d intents for %s", len(intents), story.issue_key)
    return intents


def _expand_intents_for_coverage(
    story: JiraStory,
    base_intents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    If the first-pass extraction is too narrow, ask for additional
    non-duplicate intents focused on missing coverage categories.
    """
    if not base_intents:
        return []

    base_texts = [r.get("text", "") for r in base_intents if r.get("text")]

    context_parts = [
        f"Story: {story.issue_key} - {story.summary}",
        f"Description: {story.description or story.story_description}",
    ]
    if story.new_process:
        context_parts.append(f"New Process: {story.new_process[:1200]}")
    if story.business_scenarios:
        context_parts.append(f"Business Scenarios: {story.business_scenarios[:700]}")
    if story.supplemental_comments:
        context_parts.append(f"Comments / Final Approach: {story.supplemental_comments[:700]}")
    if story.impacted_areas:
        context_parts.append(f"Impacted Areas: {story.impacted_areas[:400]}")
    if story.acceptance_criteria:
        context_parts.append(f"Acceptance Criteria: {story.acceptance_criteria[:700]}")
    context = "\n".join(x for x in context_parts if x and x.strip())

    coverage_system = (
        "You are a CAS ATDD test planner.\n"
        "Generate only additional missing concise intents.\n"
        "Output must be a JSON array of objects with keys: text, family.\n"
        "No markdown."
    )
    coverage_user = (
        "Existing intents (already approved draft):\n"
        f"{json.dumps(base_texts, ensure_ascii=False)}\n\n"
        "Story context:\n"
        f"{context}\n\n"
        "Return only NEW intents that are not duplicates.\n"
        "Focus only on missing categories among: negative, validation, boundary/data-combination,\n"
        "state-transition or persistence, and dependent-entity effects.\n"
        "No setup-only intents (login/navigation).\n"
        "Use concrete CAS terms from the story.\n"
        "Intent text length target: 6 to 14 words, one behavior only.\n"
        "Return 0 to 6 additional intents as a JSON array."
    )

    try:
        raw = llm_client.chat(
            system_prompt=coverage_system,
            user_prompt=coverage_user,
            temperature=min(LLM_TEMPERATURE, 0.2),
            max_tokens=448,
        )
    except Exception as exc:
        _log.warning("Coverage intent expansion failed for %s: %s", story.issue_key, exc)
        return []

    return _dedupe_records(_normalise_records(_parse_intent_records(raw)))


def coerce_intents(
    intents: Optional[list[Any]],
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Backward-compatible converter:
      - list[str] -> structured intents
      - list[dict] -> normalised structured intents
    """
    if not intents:
        return []

    records: list[dict[str, Any]] = []
    for item in intents:
        if isinstance(item, str):
            records.append({"text": item})
            continue
        if isinstance(item, dict):
            if item.get("text"):
                records.append(item)
                continue
        text = getattr(item, "text", None)
        if text:
            records.append(
                {
                    "id": getattr(item, "id", None),
                    "text": text,
                    "family": getattr(item, "family", None),
                    "inherit_story_scope": getattr(item, "inherit_story_scope", True),
                    "lob_scope": getattr(item, "lob_scope", None),
                    "stage_scope": getattr(item, "stage_scope", None),
                    "action_target": getattr(item, "action_target", None),
                    "screen_hint": getattr(item, "screen_hint", None),
                    "expected_outcome": getattr(item, "expected_outcome", None),
                    "entity": getattr(item, "entity", None),
                    "target_field": getattr(item, "target_field", None),
                    "expected_state": getattr(item, "expected_state", None),
                    "polarity": getattr(item, "polarity", None),
                    "must_anchor_terms": getattr(item, "must_anchor_terms", None),
                    "must_assert_terms": getattr(item, "must_assert_terms", None),
                    "forbidden_terms": getattr(item, "forbidden_terms", None),
                    "matrix_signature": getattr(item, "matrix_signature", None),
                    "allow_expansion": getattr(item, "allow_expansion", None),
                }
            )

    records = _dedupe_records(_normalise_records(records))
    return _assign_ids_and_scope(records, story_scope_defaults)


def intents_to_legacy_texts(intents: Iterable[dict[str, Any] | str]) -> list[str]:
    out: list[str] = []
    for item in intents:
        if isinstance(item, str):
            text = item.strip()
        else:
            text = str(item.get("text", "")).strip()
        if text:
            out.append(text)
    return out


def normalise_story_scope_defaults(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "lob_scope": {"mode": "all", "values": []},
            "stage_scope": {"mode": "all", "values": []},
        }

    def _norm_scope(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"mode": "all", "values": []}
        mode = str(value.get("mode", "all")).strip().lower()
        if mode not in {"all", "specific"}:
            mode = "all"
        values_raw = value.get("values", []) or []
        values: list[str] = []
        seen: set[str] = set()
        for v in values_raw:
            txt = str(v).strip()
            if not txt:
                continue
            k = txt.lower()
            if k in seen:
                continue
            seen.add(k)
            values.append(txt)
        return {"mode": mode, "values": values}

    lob = _norm_scope(raw.get("lob_scope"))
    stage = _norm_scope(raw.get("stage_scope"))
    return {"lob_scope": lob, "stage_scope": stage}


def _is_specific_scope_local(scope: dict[str, Any]) -> bool:
    return scope.get("mode") == "specific" and bool(scope.get("values"))


def _humanize_stage_tag(tag: str) -> str:
    name = str(tag or "").strip().lstrip("@")
    if not name:
        return ""
    if name.isupper():
        return name
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()


def _heading_stage_from_block(text: str) -> Optional[str]:
    for raw_line in (text or "").splitlines():
        line = raw_line.strip(" *-	")
        if not line or len(line) > 48:
            continue
        if line.endswith(":"):
            line = line[:-1].strip()
        tag = detect_stage(line)
        if tag:
            return _humanize_stage_tag(tag)
        if re.fullmatch(r"[A-Z][A-Z /_-]{2,}", line):
            lowered = line.title()
            tag = detect_stage(lowered)
            if tag:
                return _humanize_stage_tag(tag)
    return None


def infer_story_scope_defaults(story: JiraStory) -> dict[str, Any]:
    defaults = normalise_story_scope_defaults(None)
    stage_value: Optional[str] = None

    for block in (story.new_process, story.current_process, story.business_scenarios, story.acceptance_criteria):
        stage_value = _heading_stage_from_block(block)
        if stage_value:
            break

    if not stage_value:
        summary = (story.summary or "").strip()
        tail = summary.rsplit(" - ", 1)[-1].strip() if " - " in summary else summary
        tag = detect_stage(tail)
        if tag:
            stage_value = _humanize_stage_tag(tag)

    if stage_value:
        defaults["stage_scope"] = {"mode": "specific", "values": [stage_value]}

    scope_blob = "\n".join(
        part for part in (
            story.summary,
            story.new_process,
            story.current_process,
            story.business_scenarios,
            story.impacted_areas,
        )
        if part and part.strip()
    ).lower()
    lob_matches: list[str] = []
    for canonical, phrases in _lob_scope_hints():
        if any(re.search(r"\b" + re.escape(phrase) + r"\b", scope_blob, flags=re.I) for phrase in phrases):
            lob_matches.append(canonical)
    lob_matches = list(dict.fromkeys(lob_matches))
    if len(lob_matches) == 1:
        defaults["lob_scope"] = {"mode": "specific", "values": lob_matches}

    return defaults


def _story_scope_prompt_block(defaults: dict[str, Any]) -> str:
    lines: list[str] = []
    if _is_specific_scope_local(defaults.get("lob_scope", {})):
        values = ", ".join(str(v) for v in defaults["lob_scope"].get("values") or [])
        lines.append(f"Story LOB scope default: {values}")
    if _is_specific_scope_local(defaults.get("stage_scope", {})):
        values = ", ".join(str(v) for v in defaults["stage_scope"].get("values") or [])
        lines.append(f"Story stage scope default: {values}")
    if not lines:
        return ""
    lines.append("Treat these as the default scope for most intents unless the story explicitly says otherwise.")
    lines.append("Do not flip enable/disable or recommended/not recommended polarity from the story text.")
    return "Story Scope Defaults:\n" + "\n".join(f"- {line}" for line in lines) + "\n\n"


# -------------------------------------------------------------------------------
# Output parser - tolerant of LLM formatting quirks
# -------------------------------------------------------------------------------

def _strip_wrappers(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"```[a-z]*\s*", "", text).strip()
    text = re.sub(r"```", "", text).strip()
    return text


def _parse_intent_records(raw: str) -> list[dict[str, Any]]:
    """
    Parse intent output into list[{"text":..., "family":...}] while accepting:
      - array of objects
      - array of strings
      - mixed arrays
    """
    text = _strip_wrappers(raw)
    if not text:
        return []

    def _coerce(obj: Any) -> list[dict[str, Any]]:
        if not isinstance(obj, list):
            return []
        out: list[dict[str, Any]] = []
        for item in obj:
            if isinstance(item, str):
                out.append({"text": item})
            elif isinstance(item, dict):
                txt = item.get("text") or item.get("intent") or item.get("name")
                fam = item.get("family")
                if txt:
                    out.append({
                        "text": str(txt),
                        "family": str(fam) if fam else None,
                        "action_target": item.get("action_target"),
                        "screen_hint": item.get("screen_hint"),
                        "expected_outcome": item.get("expected_outcome"),
                        "entity": item.get("entity"),
                        "target_field": item.get("target_field"),
                        "expected_state": item.get("expected_state"),
                        "polarity": item.get("polarity"),
                        "must_anchor_terms": item.get("must_anchor_terms"),
                        "must_assert_terms": item.get("must_assert_terms"),
                        "forbidden_terms": item.get("forbidden_terms"),
                        "matrix_signature": item.get("matrix_signature"),
                        "allow_expansion": item.get("allow_expansion"),
                    })
        return out

    try:
        parsed = json.loads(text)
        recs = _coerce(parsed)
        if recs:
            return recs
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        array_text = re.sub(r",\s*\]", "]", m.group(0))
        try:
            parsed = json.loads(array_text)
            recs = _coerce(parsed)
            if recs:
                return recs
        except json.JSONDecodeError:
            pass

    return [{"text": t} for t in _parse_intents(raw)]


def _parse_intents(raw: str) -> list[str]:
    """
    Parse LLM output into a list of intent strings.

    Handles:
    - Clean JSON arrays
    - Arrays wrapped in markdown code fences  (```json ... ```)
    - Arrays with trailing commas
    - Plain quoted strings separated by newlines (fallback)
    """
    text = _strip_wrappers(raw)

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return _clean_list(result)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        array_text = m.group(0)
        array_text = re.sub(r",\s*\]", "]", array_text)
        try:
            result = json.loads(array_text)
            if isinstance(result, list):
                return _clean_list(result)
        except json.JSONDecodeError:
            pass

    items = re.findall(r'"([^"]{15,})"', text)
    if items:
        return items

    _log.warning("Could not parse intents from LLM output:\n%s", raw)
    return []


def _clean_list(items: list[Any]) -> list[str]:
    return [str(i).strip() for i in items if str(i).strip()]


def _dedupe_intents(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw).strip()
        if not text:
            continue
        if _is_setup_intent(text):
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _is_setup_intent(text: str) -> bool:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    blocked_prefixes = (
        "user logs in",
        "user should be able to log in",
        "user should log in",
        "user navigates to",
        "user should be able to navigate",
        "user opens the screen",
    )
    return any(t.startswith(p) for p in blocked_prefixes)


def _normalise_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in records:
        raw_text = str((rec or {}).get("text", "")).strip()
        if not raw_text:
            continue
        text = _normalise_intent_text(raw_text)
        if not text:
            continue
        if _is_setup_intent(text):
            continue
        if _is_generic_intent(text):
            continue
        family = _normalise_family((rec or {}).get("family"), text)
        hints = _planning_hints_for_text(text, rec)
        out.append({
            "text": text,
            "family": family,
            "action_target": hints.get("action_target"),
            "screen_hint": hints.get("screen_hint"),
            "expected_outcome": hints.get("expected_outcome"),
            "entity": rec.get("entity"),
            "target_field": rec.get("target_field"),
            "expected_state": rec.get("expected_state"),
            "polarity": rec.get("polarity"),
            "must_anchor_terms": rec.get("must_anchor_terms"),
            "must_assert_terms": rec.get("must_assert_terms"),
            "forbidden_terms": rec.get("forbidden_terms"),
            "matrix_signature": rec.get("matrix_signature"),
            "allow_expansion": rec.get("allow_expansion"),
        })
    return out


def _dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for rec in records:
        text = str(rec.get("text", "")).strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text.lower())
        if key in seen:
            continue

        too_similar = False
        for existing in out:
            ratio = SequenceMatcher(None, key, existing["text"].lower()).ratio()
            if ratio >= 0.90:
                too_similar = True
                break
        if too_similar:
            continue

        seen.add(key)
        out.append({
            "text": text,
            "family": rec.get("family", "positive"),
            "action_target": rec.get("action_target"),
            "screen_hint": rec.get("screen_hint"),
            "expected_outcome": rec.get("expected_outcome"),
            "entity": rec.get("entity"),
            "target_field": rec.get("target_field"),
            "expected_state": rec.get("expected_state"),
            "polarity": rec.get("polarity"),
            "must_anchor_terms": rec.get("must_anchor_terms"),
            "must_assert_terms": rec.get("must_assert_terms"),
            "forbidden_terms": rec.get("forbidden_terms"),
            "matrix_signature": rec.get("matrix_signature"),
            "allow_expansion": rec.get("allow_expansion"),
        })

    return out


def _assign_ids_and_scope(
    records: list[dict[str, Any]],
    story_scope_defaults: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    _ = normalise_story_scope_defaults(story_scope_defaults)
    out: list[dict[str, Any]] = []
    for idx, rec in enumerate(records, 1):
        out.append(
            {
                "id": rec.get("id") or f"intent_{idx:03d}",
                "text": rec["text"],
                "family": rec.get("family", "positive"),
                "inherit_story_scope": bool(rec.get("inherit_story_scope", True)),
                "lob_scope": rec.get("lob_scope"),
                "stage_scope": rec.get("stage_scope"),
                "action_target": rec.get("action_target"),
                "screen_hint": rec.get("screen_hint"),
                "expected_outcome": rec.get("expected_outcome"),
                "entity": rec.get("entity"),
                "target_field": rec.get("target_field"),
                "expected_state": rec.get("expected_state"),
                "polarity": rec.get("polarity"),
                "must_anchor_terms": list(rec.get("must_anchor_terms") or []),
                "must_assert_terms": list(rec.get("must_assert_terms") or []),
                "forbidden_terms": list(rec.get("forbidden_terms") or []),
                "matrix_signature": rec.get("matrix_signature"),
                "allow_expansion": bool(rec.get("allow_expansion", False)),
            }
        )
    return out


def _planning_hints_for_text(text: str, rec: dict[str, Any]) -> dict[str, Any]:
    action_target = _clean_hint_text(rec.get("action_target")) or _derive_action_target(text)
    screen_hint = _clean_hint_text(rec.get("screen_hint")) or _derive_screen_hint(text)
    expected_outcome = _clean_hint_text(rec.get("expected_outcome")) or _derive_expected_outcome(text)
    return {
        "action_target": action_target,
        "screen_hint": screen_hint,
        "expected_outcome": expected_outcome,
    }


def _clean_hint_text(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if text else None


def _derive_action_target(text: str) -> Optional[str]:
    words = re.findall(r"[A-Za-z0-9']+", text)
    if not words:
        return None

    lowered = [w.lower() for w in words]
    start = 0
    while start < len(lowered) and lowered[start] in {"the", "a", "an"}:
        start += 1
    if start < len(lowered) and lowered[start] in _INTENT_VERBS:
        start += 1

    stop_words = {"when", "after", "before", "for", "on", "at", "if", "with", "during"}
    selected: list[str] = []
    for word in words[start:]:
        if word.lower() in stop_words and selected:
            break
        if word.lower() in _INTENT_FILLER and selected:
            continue
        selected.append(word)
        if len(selected) >= 5:
            break

    if not selected:
        return None
    return " ".join(selected).strip()


def _derive_screen_hint(text: str) -> Optional[str]:
    patterns = (
        r"on ([A-Za-z0-9 /_-]{3,40}?) screen",
        r"at ([A-Za-z0-9 /_-]{3,40}?) screen",
        r"in ([A-Za-z0-9 /_-]{3,40}?) screen",
        r"on ([A-Za-z0-9 /_-]{3,40}?) page",
        r"at ([A-Za-z0-9 /_-]{3,40}?) page",
    )
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" -")
    return None


def _derive_expected_outcome(text: str) -> Optional[str]:
    tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9']+", text)}
    for outcome, hints in _OUTCOME_HINT_MAP:
        if tokens & hints:
            return outcome
    return None


def _normalise_intent_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"^(user|system|the\s+\w+\s+screen)\s+should\s+be\s+able\s+to\s+", "", t, flags=re.I)
    t = re.sub(r"^(user|system|the\s+\w+\s+screen)\s+should\s+", "", t, flags=re.I)
    t = t.strip(" .-")
    if not t:
        return ""

    words = re.findall(r"[A-Za-z0-9']+", t)
    if len(words) > 14:
        compact: list[str] = []
        for w in words:
            lw = w.lower()
            if lw in _INTENT_FILLER and len(words) - len(compact) > 6:
                continue
            compact.append(w)
            if len(compact) >= 14:
                break
        if compact:
            t = " ".join(compact)

    return t


def _is_generic_intent(text: str) -> bool:
    low = text.lower()
    if any(p in low for p in _GENERIC_PATTERNS):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", low)]
    if len(words) < 4:
        return True
    return False


def _normalise_family(raw_family: Any, text: str) -> str:
    if raw_family is not None:
        key = str(raw_family).strip().lower().replace(" ", "_")
        fam = _FAMILY_ALIASES.get(key)
        if fam in _VALID_FAMILIES:
            return fam
    inferred = _infer_family(text)
    return inferred if inferred in _VALID_FAMILIES else "positive"


def _infer_family(text: str) -> str:
    low = text.lower()
    if any(h in low for h in _NEGATIVE_HINTS):
        return "negative"
    if any(h in low for h in _VALIDATION_HINTS):
        return "validation"
    if any(h in low for h in _DEPENDENCY_HINTS):
        return "dependency"
    if any(h in low for h in _PERSIST_HINTS):
        return "persistence"
    if any(h in low for h in _STATE_HINTS):
        return "state_movement"
    if any(h in low for h in _DATA_HINTS):
        return "data_combination"
    if any(h in low for h in _EDGE_HINTS):
        return "edge"
    return "positive"





