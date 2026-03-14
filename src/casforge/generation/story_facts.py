from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from casforge.generation import llm_client
from casforge.parsing.jira_parser import JiraStory
from casforge.shared.paths import PROMPTS_DIR
from casforge.shared.settings import LLM_MAX_TOKENS, LLM_TEMPERATURE
from casforge.workflow.ordering import detect_stage

_log = logging.getLogger(__name__)

_PROMPT_FILE = PROMPTS_DIR / "extract_story_facts.txt"

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

_VALID_EFFECTS = {
    "display",
    "enable",
    "disable",
    "derive",
    "validate",
    "default_state",
    "state_move",
    "persistence",
    "zero_validation",
    "selection_dependency",
}

_VALID_POLARITIES = {
    "positive",
    "negative",
    "enabled",
    "disabled",
    "checked",
    "unchecked",
    "recommended",
    "not_recommended",
    "allowed",
    "not_allowed",
    "derived",
    "retained",
    "moved",
    "zero_allowed",
    "zero_not_allowed",
}

_VALID_COVERAGE_SIGNALS = {
    "ui_structure",
    "default_state",
    "dependency",
    "field_enablement",
    "derived_decision",
    "validation",
    "state_movement",
    "persistence",
    "data_combination",
    "edge",
}

_VALID_MATRIX_SIGNALS = {
    "any",
    "all",
    "none",
    "mixed",
    "dependent_card",
    "zero_value",
    "multi_grid",
}

_EFFECT_ALIASES = {
    "visible": "display",
    "show": "display",
    "shown": "display",
    "displayed": "display",
    "enabled": "enable",
    "disabled": "disable",
    "derived": "derive",
    "calculated": "derive",
    "validation": "validate",
    "mandatory": "validate",
    "state_movement": "state_move",
    "movement": "state_move",
    "move": "state_move",
    "persist": "persistence",
    "retain": "persistence",
}

_FAMILY_ALIASES = {
    "core": "positive",
    "happy_path": "positive",
    "rejection": "negative",
    "mandatory": "validation",
    "dependent": "dependency",
    "state": "state_movement",
    "movement": "state_movement",
    "save": "persistence",
    "boundary": "data_combination",
    "combination": "data_combination",
}

_POLARITY_ALIASES = {
    "enable": "enabled",
    "disable": "disabled",
    "recommend": "recommended",
    "reject": "negative",
    "move": "moved",
    "persist": "retained",
    "retain": "retained",
    "zero_disallowed": "zero_not_allowed",
    "zero_disabled": "zero_not_allowed",
}

_LOB_SCOPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("OMNI", ("omni loan", "omni")),
    ("HL", ("home loan",)),
    ("PL", ("personal loan",)),
    ("LAP", ("loan against property", "lap")),
    ("MHL", ("micro home loan", "mhl")),
    ("CV", ("commercial vehicle", "consumer vehicle", "cv")),
    ("EDU", ("education loan", "education", "edu")),
    ("PF", ("personal finance", "pf")),
    ("BL", ("business loan", "bl")),
)

_ENTITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("decision column", ("decision column", "column decision", "new column decision", "new column 'decision'", 'new column "decision"')), 
    ("decision checkbox", ("decision checkbox", "checkbox in decision column", "decision check box", "decision checkbox")),
    ("recommendation decision dropdown", ("recommendation decision dropdown", "recommendation decision", "application level decision", "application decision")),
    ("sub product decision", ("sub product decision", "sub loan decision", "separate decision", "sub loan level decision", "separate recommendation decision")),
    ("recommended amount", ("recommended amount",)),
    ("recommended limit", ("recommended limit", "recommended limit field")),
    ("primary card", ("primary card",)),
    ("add-on card", ("add-on card", "addon card", "add on card")),
    ("product type decision list", ("product type decision list",)),
    ("mtns", ("mtns", "move to next stage", "move next")),
    ("sub loan", ("sub loan", "subloan", "sub loans", "subloans")),
    ("credit card grid", ("credit card grid", "credit card", "card grid")),
    ("committee verdict", ("committee verdict", "committee decision", "verdict")),
)

_COVERAGE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ui_structure", ("new column", "display", "show", "visible", "grid", "screen", "accordion")),
    ("default_state", ("by default", "default", "checked", "unchecked")),
    ("dependency", ("if any", "if all", "based on", "depending on", "derived from", "same as")),
    ("field_enablement", ("enable", "enabled", "disable", "disabled", "editable", "read only", "readonly")),
    ("derived_decision", ("derive", "derived", "calculated", "decision should be same", "application will")),
    ("validation", ("validation", "mandatory", "required", "error", "reject", "invalid", "zero")),
    ("state_movement", ("move to", "move next", "next stage", "credit approval", "recommendation", "committee approval", "disbursal")),
    ("persistence", ("save", "saved", "retain", "retained", "reopen", "persist")),
    ("data_combination", ("combination", "multiple", "both", "all", "any", "none")),
    ("edge", ("zero", "none", "mixed", "duplicate", "blank", "null")),
)

_MATRIX_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("any", ("if any", "any subloan", "any sub loan", "at least one")),
    ("all", ("if all", "all subloans", "all sub loans", "all the subloans")),
    ("none", ("if none", "no subloan", "none selected", "no majority")),
    ("mixed", ("mixed", "tie", "combination", "split")),
    ("dependent_card", ("primary card", "add-on card", "addon card", "add on card")),
    ("zero_value", ("zero", "0 value", "0 amount", "amt to be zero")),
    ("multi_grid", ("both subloan and credit card grids", "both subloan and credit card", "both grids", "credit card grids")),
)


def extract_story_facts(
    story: JiraStory,
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    defaults = _normalise_story_scope_defaults(story_scope_defaults) or _infer_scope_defaults(story)
    heuristic = infer_story_facts_heuristically(story, defaults)
    if _heuristic_facts_are_authoritative(heuristic):
        return heuristic

    llm_facts: dict[str, Any] = {}
    try:
        system_prompt, user_template = _load_prompt()
        user_prompt = user_template.format(
            key=story.issue_key,
            summary=story.summary,
            description=story.description or story.story_description,
            new_process_block=_block("New Behavior to Implement", story.new_process, 1600),
            business_scenarios_block=_block("Business Scenarios / Exceptions", story.business_scenarios, 900),
            impacted_areas_block=_block("Impacted CAS Areas / Stages", story.impacted_areas, 500),
            key_ui_block=_block("Key UI Navigation", story.key_ui_steps, 500),
            acceptance_criteria_block=_block("Acceptance Criteria", story.acceptance_criteria, 900),
            story_scope_block=_story_scope_prompt_block(defaults),
        )
        raw = llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=min(LLM_TEMPERATURE, 0.15),
            max_tokens=max(640, min(LLM_MAX_TOKENS, 1200)),
        )
        llm_facts = _normalise_story_facts(_parse_story_facts(raw), story, defaults)
    except Exception as exc:
        _log.warning("Story facts LLM extraction failed for %s: %s", story.issue_key, exc)

    merged = _merge_story_facts(heuristic, llm_facts, story, defaults)
    return _prune_contradictions(merged)


def infer_story_facts_heuristically(story: JiraStory, defaults: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    defaults = _normalise_story_scope_defaults(defaults) or _infer_scope_defaults(story)
    blob = _story_blob(story)
    entities = _detect_entities(blob)
    rules = list(_seed_precision_rules(story, defaults))
    for sentence in _candidate_rule_sentences(story):
        rule = _heuristic_rule(sentence, defaults, story)
        if rule:
            rules.append(rule)
    rules = _dedupe_rules([rule for rule in rules if not _rule_is_noise(rule)])
    coverage_signals = _detect_coverage_signals(blob, rules)
    matrix_signals = _detect_matrix_signals(blob, rules)
    return _normalise_story_facts(
        {
            "story_scope_defaults": defaults,
            "entities": entities,
            "rules": rules,
            "coverage_signals": coverage_signals,
            "matrix_signals": matrix_signals,
        },
        story,
        defaults,
    )



def _seed_precision_rules(story: JiraStory, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    blob = _story_blob(story)
    rules: list[dict[str, Any]] = []
    stage_scope = defaults.get("stage_scope")
    lob_scope = defaults.get("lob_scope")

    def _rule(*, condition: str, target: str, effect: str, polarity: str, family_hint: str, screen_hint: Optional[str] = None, stage=None, lob=None):
        rule = {
            "condition": _clean_sentence(condition),
            "target": target,
            "effect": effect,
            "polarity": polarity,
            "family_hint": family_hint,
        }
        if screen_hint:
            rule["screen_hint"] = screen_hint
        if stage:
            rule["stage_scope"] = stage
        if lob:
            rule["lob_scope"] = lob
        return rule

    if "product type decision list" in blob and "new column" in blob and "decision" in blob:
        rules.append(_rule(
            condition="at recommendation stage in product type decision list",
            target="decision column",
            effect="display",
            polarity="positive",
            family_hint="positive",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if "it will be a checkbox" in blob or ("decision" in blob and "checkbox" in blob):
        rules.append(_rule(
            condition="for applicable sub products in product type decision list",
            target="decision checkbox",
            effect="display",
            polarity="enabled",
            family_hint="positive",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if "by default" in blob and "check" in blob:
        rules.append(_rule(
            condition="when user lands on recommendation stage",
            target="decision checkbox",
            effect="default_state",
            polarity="checked",
            family_hint="positive",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if "both subloan and credit card grids" in blob or "both subloan and credit card" in blob:
        rules.append(_rule(
            condition="for subloan grid",
            target="decision checkbox for sub loan grid",
            effect="display",
            polarity="positive",
            family_hint="positive",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
        rules.append(_rule(
            condition="for credit card grid",
            target="decision checkbox for credit card grid",
            effect="display",
            polarity="positive",
            family_hint="data_combination",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if "if any subloan is not recommended" in blob and "recommended limit field" in blob and "disabled" in blob:
        rules.append(_rule(
            condition="if any subloan is not recommended",
            target="recommended limit field",
            effect="disable",
            polarity="disabled",
            family_hint="dependency",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if ("application level decision" in blob or "application decision" in blob) and "selected as recommended" in blob:
        rules.append(_rule(
            condition="if any sub product checkbox is checked",
            target="recommendation decision dropdown",
            effect="derive",
            polarity="recommended",
            family_hint="dependency",
            screen_hint="Recommendation Decisions",
            stage=stage_scope,
            lob=lob_scope,
        ))
        rules.append(_rule(
            condition="after sub product checkbox selection",
            target="recommendation decision dropdown",
            effect="disable",
            polarity="disabled",
            family_hint="dependency",
            screen_hint="Recommendation Decisions",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if "all the subloans are marked not recommended" in blob and ("application decision will be updated to not recommended" in blob or "application level decision" in blob):
        rules.append(_rule(
            condition="if all sub product checkboxes are unchecked",
            target="recommendation decision dropdown",
            effect="derive",
            polarity="not_recommended",
            family_hint="dependency",
            screen_hint="Recommendation Decisions",
            stage=stage_scope,
            lob=lob_scope,
        ))
    if ("move to next stage" in blob or "move to credit approval" in blob or "move to credit approval" in blob) and ("mtns" in blob or "move to next stage" in blob or "credit approval" in blob):
        rules.append(_rule(
            condition="on MTNS from recommendation stage",
            target="credit approval stage",
            effect="state_move",
            polarity="moved",
            family_hint="state_movement",
            screen_hint="Product Type Decision List",
            stage=stage_scope,
            lob=lob_scope,
        ))
    return rules


def _rule_is_noise(rule: dict[str, Any]) -> bool:
    target = str(rule.get("target", "")).strip().lower()
    condition = str(rule.get("condition", "")).strip().lower()
    effect = str(rule.get("effect", "")).strip().lower()
    if target in {"this field", "application", "omni loan"}:
        return True
    if target == "sub loan" and effect == "display":
        return True
    if condition.startswith("where separate") and effect == "display":
        return True
    return False


def _load_prompt() -> tuple[str, str]:
    content = _PROMPT_FILE.read_text(encoding="utf-8")
    parts = content.split("\nUSER:\n", 1)
    if len(parts) != 2:
        raise ValueError(f"Prompt file {_PROMPT_FILE} must contain a 'USER:' section")
    system = parts[0].replace("SYSTEM:\n", "", 1).strip()
    user_template = parts[1].strip()
    return system, user_template


def _block(title: str, text: str, limit: int) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    clipped = body[:limit]
    if len(body) > limit:
        clipped += "\n[...truncated...]"
    return f"{title}:\n{clipped}\n\n"


def _story_scope_prompt_block(defaults: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, label in (("lob_scope", "LOB"), ("stage_scope", "stage")):
        scope = defaults.get(key, {})
        if scope.get("mode") == "specific" and scope.get("values"):
            lines.append(f"Default {label} scope: {', '.join(scope['values'])}")
    if not lines:
        return ""
    return "Story Scope Defaults:\n" + "\n".join(f"- {line}" for line in lines) + "\n\n"


def _parse_story_facts(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"```[a-z]*\s*", "", text).strip()
    text = re.sub(r"```", "", text).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        candidate = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalise_story_facts(raw: Optional[dict[str, Any]], story: JiraStory, defaults: Optional[dict[str, Any]]) -> dict[str, Any]:
    defaults = _normalise_story_scope_defaults(defaults) or _infer_scope_defaults(story)
    data = raw if isinstance(raw, dict) else {}
    result = {
        "story_scope_defaults": _normalise_story_scope_defaults(data.get("story_scope_defaults")) or defaults,
        "entities": _normalise_entities(data.get("entities")),
        "rules": _normalise_rules(data.get("rules"), story, defaults),
        "coverage_signals": _normalise_signal_list(data.get("coverage_signals"), _VALID_COVERAGE_SIGNALS),
        "matrix_signals": _normalise_signal_list(data.get("matrix_signals"), _VALID_MATRIX_SIGNALS),
    }

    if not result["entities"]:
        result["entities"] = _detect_entities(_story_blob(story))
    if not result["coverage_signals"]:
        result["coverage_signals"] = _detect_coverage_signals(_story_blob(story), result["rules"])
    if not result["matrix_signals"]:
        result["matrix_signals"] = _detect_matrix_signals(_story_blob(story), result["rules"])
    return result


def _merge_story_facts(base: dict[str, Any], overlay: dict[str, Any], story: JiraStory, defaults: dict[str, Any]) -> dict[str, Any]:
    base_norm = _normalise_story_facts(base, story, defaults)
    overlay_norm = _normalise_story_facts(overlay, story, defaults)

    merged_defaults = dict(base_norm["story_scope_defaults"])
    overlay_defaults = overlay_norm["story_scope_defaults"]
    for key in ("lob_scope", "stage_scope"):
        if (
            merged_defaults.get(key, {}).get("mode") != "specific"
            and overlay_defaults.get(key, {}).get("mode") == "specific"
            and overlay_defaults.get(key, {}).get("values")
        ):
            merged_defaults[key] = overlay_defaults[key]

    merged = {
        "story_scope_defaults": merged_defaults,
        "entities": _unique(base_norm["entities"] + overlay_norm["entities"]),
        "rules": _dedupe_rules(base_norm["rules"] + overlay_norm["rules"]),
        "coverage_signals": _unique(base_norm["coverage_signals"] + overlay_norm["coverage_signals"]),
        "matrix_signals": _unique(base_norm["matrix_signals"] + overlay_norm["matrix_signals"]),
    }
    return _normalise_story_facts(merged, story, defaults)


def _prune_contradictions(facts: dict[str, Any]) -> dict[str, Any]:
    contradictory_keys: set[tuple[str, str, str]] = set()
    polarity_by_key: dict[tuple[str, str, str], str] = {}
    for rule in facts.get("rules", []):
        key = (
            _norm_text(rule.get("target")),
            _norm_text(rule.get("effect")),
            _condition_signature(rule.get("condition")),
        )
        polarity = _norm_text(rule.get("polarity"))
        if not key[0] or not key[1] or not polarity:
            continue
        existing = polarity_by_key.get(key)
        if existing and existing != polarity:
            contradictory_keys.add(key)
        else:
            polarity_by_key[key] = polarity

    if contradictory_keys:
        facts = dict(facts)
        facts["rules"] = [
            rule for rule in facts.get("rules", [])
            if (
                _norm_text(rule.get("target")),
                _norm_text(rule.get("effect")),
                _condition_signature(rule.get("condition")),
            ) not in contradictory_keys
        ]
    return facts


def _heuristic_facts_are_authoritative(facts: dict[str, Any]) -> bool:
    rules = list(facts.get("rules") or [])
    if not rules:
        return False

    families = {
        _norm_text(rule.get("family_hint"))
        for rule in rules
        if _norm_text(rule.get("family_hint"))
    }
    entities = {
        _norm_text(entity)
        for entity in (facts.get("entities") or [])
        if _norm_text(entity)
    }
    coverage = {
        _norm_text(signal)
        for signal in (facts.get("coverage_signals") or [])
        if _norm_text(signal)
    }

    if len(rules) >= 8 and len(families) >= 3:
        return True
    if len(rules) >= 6 and len(families) >= 3 and len(coverage) >= 3 and len(entities) >= 2:
        return True
    return False


def _normalise_entities(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else []
    entities: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" .-")
        if not text:
            continue
        canonical = _canonical_entity(text)
        entities.append(canonical or text)
    return _unique(entities)


def _canonical_entity(text: str) -> Optional[str]:
    lowered = text.lower()
    for canonical, phrases in _ENTITY_PATTERNS:
        if lowered == canonical or any(phrase in lowered for phrase in phrases):
            return canonical
    return None


def _normalise_rules(raw: Any, story: JiraStory, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    values = raw if isinstance(raw, list) else []
    rules: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        condition = _clean_sentence(value.get("condition"))
        target = _clean_sentence(value.get("target"))
        effect = _normalise_effect(value.get("effect"), condition, target)
        polarity = _normalise_polarity(value.get("polarity"), effect, condition, target)
        family_hint = _normalise_family(value.get("family_hint"), effect, polarity, condition, target)
        if not target:
            target = _infer_target_from_text(" ".join(part for part in (condition, target) if part))
        if not effect:
            effect = _infer_effect(" ".join(part for part in (condition, target) if part))
        if not polarity:
            polarity = _normalise_polarity(None, effect, condition, target)
        if not family_hint:
            family_hint = _normalise_family(None, effect, polarity, condition, target)
        if not target or not effect or not family_hint:
            continue
        rule = {
            "condition": condition,
            "target": target,
            "effect": effect,
            "polarity": polarity or "positive",
            "family_hint": family_hint,
        }
        if value.get("stage_scope"):
            rule["stage_scope"] = _normalise_story_scope_defaults({"stage_scope": value.get("stage_scope")}).get("stage_scope")
        if value.get("lob_scope"):
            rule["lob_scope"] = _normalise_story_scope_defaults({"lob_scope": value.get("lob_scope")}).get("lob_scope")
        if value.get("screen_hint"):
            rule["screen_hint"] = _clean_sentence(value.get("screen_hint"))
        rules.append(rule)

    if not rules:
        for sentence in _candidate_rule_sentences(story):
            rule = _heuristic_rule(sentence, defaults, story)
            if rule and not _rule_is_noise(rule):
                rules.append(rule)
    return _dedupe_rules([rule for rule in rules if not _rule_is_noise(rule)])


def _normalise_effect(raw: Any, *fallback_parts: str) -> Optional[str]:
    text = _norm_text(raw)
    text = _EFFECT_ALIASES.get(text, text)
    if text in _VALID_EFFECTS:
        return text
    combined = " ".join(part for part in fallback_parts if part)
    inferred = _infer_effect(combined)
    return inferred if inferred in _VALID_EFFECTS else None


def _normalise_polarity(raw: Any, effect: Optional[str], *fallback_parts: str) -> Optional[str]:
    text = _norm_text(raw)
    text = _POLARITY_ALIASES.get(text, text)
    if text in _VALID_POLARITIES:
        return text

    blob = " ".join(part for part in fallback_parts if part).lower()
    if effect == "disable" or re.search(r"\bdisabled?\b|read ?only|not editable", blob):
        return "disabled"
    if effect == "enable" or re.search(r"\benabled?\b|editable", blob):
        return "enabled"
    if effect == "default_state":
        if "unchecked" in blob:
            return "unchecked"
        return "checked" if "check" in blob else "positive"
    if effect == "state_move":
        return "moved"
    if effect == "persistence":
        return "retained"
    if effect == "zero_validation":
        return "zero_not_allowed" if re.search(r"not allow|prevent|error|invalid|reject", blob) else "zero_allowed"
    if "not recommended" in blob or "is not recommended" in blob:
        return "not_recommended"
    if "recommended" in blob:
        return "recommended"
    if re.search(r"reject|prevent|invalid|error|mandatory|required|not allow|must not", blob):
        return "negative"
    return "positive" if blob else None


def _normalise_family(raw: Any, effect: Optional[str], polarity: Optional[str], *fallback_parts: str) -> Optional[str]:
    text = _norm_text(raw)
    text = _FAMILY_ALIASES.get(text, text)
    if text in _VALID_FAMILIES:
        return text
    if effect in {"validate", "zero_validation"}:
        return "validation"
    if effect in {"enable", "disable", "derive", "selection_dependency"}:
        return "dependency"
    if effect == "state_move":
        return "state_movement"
    if effect == "persistence":
        return "persistence"
    if polarity in {"negative", "not_allowed", "zero_not_allowed", "not_recommended"}:
        return "negative"
    blob = " ".join(part for part in fallback_parts if part).lower()
    if re.search(r"mandatory|required|validation|invalid|error|zero", blob):
        return "validation"
    if re.search(r"if any|if all|based on|same as|derived", blob):
        return "dependency"
    if re.search(r"move to|next stage|credit approval|recommendation", blob):
        return "state_movement"
    if re.search(r"save|reopen|retain|persist", blob):
        return "persistence"
    if re.search(r"duplicate|blank|null|edge|mixed|tie", blob):
        return "edge"
    return "positive" if blob else None


def _detect_coverage_signals(blob: str, rules: list[dict[str, Any]]) -> list[str]:
    text = (blob or "").lower()
    signals: list[str] = []
    for signal, phrases in _COVERAGE_PATTERNS:
        if any(phrase in text for phrase in phrases):
            signals.append(signal)
    for rule in rules:
        family = rule.get("family_hint")
        effect = rule.get("effect")
        if family == "validation":
            signals.append("validation")
        if family == "dependency":
            signals.append("dependency")
        if family == "state_movement":
            signals.append("state_movement")
        if family == "persistence":
            signals.append("persistence")
        if effect == "default_state":
            signals.append("default_state")
        if effect in {"enable", "disable"}:
            signals.append("field_enablement")
        if effect == "derive":
            signals.append("derived_decision")
        if effect == "display":
            signals.append("ui_structure")
    return _unique(signal for signal in signals if signal in _VALID_COVERAGE_SIGNALS)


def _detect_matrix_signals(blob: str, rules: list[dict[str, Any]]) -> list[str]:
    text = (blob or "").lower()
    signals: list[str] = []
    for signal, phrases in _MATRIX_PATTERNS:
        if any(phrase in text for phrase in phrases):
            signals.append(signal)
    for rule in rules:
        cond = str(rule.get("condition", "")).lower()
        if "if any" in cond or "at least one" in cond:
            signals.append("any")
        if "if all" in cond or "all subloans" in cond or "all the subloans" in cond:
            signals.append("all")
        if "if none" in cond or "no subloan" in cond:
            signals.append("none")
    return _unique(signal for signal in signals if signal in _VALID_MATRIX_SIGNALS)


def _candidate_rule_sentences(story: JiraStory) -> list[str]:
    lines: list[str] = []
    for block in (story.new_process, story.business_scenarios, story.acceptance_criteria, story.story_description, story.description):
        if not block:
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip(" -*\t")
            if not line:
                continue
            pieces = re.split(r"(?<=[.;])\s+|\s+\*\s+", line)
            for piece in pieces:
                cleaned = _clean_sentence(piece)
                if cleaned:
                    lines.append(cleaned)
    return _unique(lines)


def _heuristic_rule(sentence: str, defaults: dict[str, Any], story: JiraStory) -> Optional[dict[str, Any]]:
    text = _clean_sentence(sentence)
    if not text:
        return None
    lowered = text.lower()
    if len(re.findall(r"[a-z0-9]+", lowered)) < 4:
        return None
    if not any(token in lowered for token in (
        "decision", "checkbox", "column", "field", "stage", "grid", "save", "retain", "persist", "recommended", "vote", "verdict", "enable", "disable", "mandatory", "zero", "move",
    )):
        return None

    target = _infer_target_from_text(text, defaults)
    effect = _infer_effect(text)
    polarity = _normalise_polarity(None, effect, text)
    family = _normalise_family(None, effect, polarity, text)
    if not target or not effect or not family:
        return None

    rule: dict[str, Any] = {
        "condition": _extract_condition(text),
        "target": target,
        "effect": effect,
        "polarity": polarity or "positive",
        "family_hint": family,
    }

    screen_hint = _infer_screen_hint_from_story(story, text)
    if screen_hint:
        rule["screen_hint"] = screen_hint

    if defaults.get("stage_scope", {}).get("mode") == "specific" and ("move to" in lowered or "move to next stage" in lowered or "mtns" in lowered):
        rule["stage_scope"] = defaults.get("stage_scope")
    else:
        stage_scope = _extract_stage_scope(text)
        if stage_scope:
            rule["stage_scope"] = {"mode": "specific", "values": [stage_scope]}
    lob_scope = _extract_lob_scope(text)
    if lob_scope:
        rule["lob_scope"] = {"mode": "specific", "values": [lob_scope]}
    return rule


def _extract_condition(text: str) -> str:
    lowered = text.lower()
    for marker in ("if ", "when ", "where ", "once ", "after "):
        idx = lowered.find(marker)
        if idx >= 0:
            return _clean_sentence(text[idx:])
    return _clean_sentence(text)


def _infer_target_from_text(text: str, defaults: Optional[dict[str, Any]] = None) -> Optional[str]:
    lowered = text.lower()
    stage_value = _primary_scope_value((defaults or {}).get("stage_scope"))
    if ("new column" in lowered or "column" in lowered) and "decision" in lowered:
        return "decision column"
    if "checkbox" in lowered or "check box" in lowered:
        if "credit card" in lowered or "card grid" in lowered:
            return "decision checkbox for credit card grid"
        if "subloan" in lowered or "sub loan" in lowered:
            return "decision checkbox for sub loan grid"
        return "decision checkbox"
    if "recommended limit" in lowered:
        return "recommended limit field"
    if "recommended amount" in lowered and "column" not in lowered:
        return "recommended amount field"
    if "application level decision" in lowered or "application decision" in lowered:
        if stage_value == "Recommendation":
            return "recommendation decision dropdown"
        return "application level decision"
    if "product type decision list" in lowered:
        return "product type decision list"
    for canonical, phrases in _ENTITY_PATTERNS:
        if any(phrase in lowered for phrase in phrases):
            return canonical
    direct_patterns = (
        r"([a-z][a-z0-9 /'-]{2,40}? field)",
        r"([a-z][a-z0-9 /'-]{2,40}? column)",
        r"([a-z][a-z0-9 /'-]{2,40}? checkbox)",
        r"([a-z][a-z0-9 /'-]{2,40}? verdict)",
    )
    for pattern in direct_patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(1).strip()
    if "stage" in lowered and "move" in lowered:
        return "application stage movement"
    return None


def _infer_effect(text: str) -> Optional[str]:
    lowered = text.lower()
    if re.search(r"\bdisabled?\b|read ?only|not editable", lowered):
        return "disable"
    if re.search(r"\benabled?\b|editable", lowered):
        return "enable"
    if "by default" in lowered or "default" in lowered and ("checked" in lowered or "unchecked" in lowered):
        return "default_state"
    if re.search(r"\bdisplay\b|\bvisible\b|\bshow\b|new column|column", lowered):
        return "display"
    if re.search(r"\bderive\b|\bderived\b|\bcalculated\b|same as", lowered):
        return "derive"
    if re.search(r"\bmove to\b|\bmove next\b|next stage|credit approval|recommendation", lowered):
        return "state_move"
    if re.search(r"\bsave\b|\bretain\b|\bretained\b|\breopen\b|\bpersist", lowered):
        return "persistence"
    if "zero" in lowered:
        return "zero_validation"
    if re.search(r"mandatory|required|validation|invalid|error|reject|prevent|duplicate", lowered):
        return "validate"
    if re.search(r"based on|depending on|if any|if all|same as", lowered):
        return "selection_dependency"
    return None


def _infer_screen_hint_from_story(story: JiraStory, text: str) -> Optional[str]:
    for source in (text, story.key_ui_steps, story.impacted_areas, story.summary):
        hint = _extract_screen_hint(source)
        if hint:
            return hint
    return None


def _extract_screen_hint(text: str) -> Optional[str]:
    if not text:
        return None
    if ">>" in text:
        parts = [part.strip() for part in text.split(">>") if part.strip()]
        if parts:
            return parts[-1]
    for pattern in (
        r"on ([A-Za-z0-9 /_-]{3,50}?) screen",
        r"at ([A-Za-z0-9 /_-]{3,50}?) stage",
        r"in ([A-Za-z0-9 /_-]{3,50}?) grid",
        r"in ([A-Za-z0-9 /_-]{3,50}?) section",
    ):
        match = re.search(pattern, text, flags=re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" -")
    return None


def _extract_stage_scope(text: str) -> Optional[str]:
    tag = detect_stage(text)
    if tag:
        return _humanize_stage_tag(tag)
    return None


def _extract_lob_scope(text: str) -> Optional[str]:
    lowered = text.lower()
    for canonical, phrases in _LOB_SCOPE_HINTS:
        if any(re.search(r"\b" + re.escape(phrase) + r"\b", lowered, flags=re.I) for phrase in phrases):
            return canonical
    return None


def _primary_scope_value(scope: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(scope, dict):
        return None
    values = scope.get("values") or []
    if not values:
        return None
    return str(values[0]).strip() or None


def _humanize_stage_tag(tag: str) -> str:
    name = str(tag or "").strip().lstrip("@")
    if not name:
        return ""
    if name.isupper():
        return name
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()


def _infer_scope_defaults(story: JiraStory) -> dict[str, Any]:
    defaults = {
        "lob_scope": {"mode": "all", "values": []},
        "stage_scope": {"mode": "all", "values": []},
    }

    stage_value: Optional[str] = None
    for block in (story.new_process, story.current_process, story.business_scenarios, story.acceptance_criteria):
        for raw_line in (block or "").splitlines():
            line = raw_line.strip(" *-\t")
            if not line or len(line) > 48:
                continue
            candidate = line[:-1].strip() if line.endswith(":") else line
            tag = detect_stage(candidate)
            if tag:
                stage_value = _humanize_stage_tag(tag)
                break
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

    blob = _story_blob(story)
    lob_matches: list[str] = []
    for canonical, phrases in _LOB_SCOPE_HINTS:
        if any(re.search(r"\b" + re.escape(phrase) + r"\b", blob, flags=re.I) for phrase in phrases):
            lob_matches.append(canonical)
    lob_matches = _unique(lob_matches)
    if len(lob_matches) == 1:
        defaults["lob_scope"] = {"mode": "specific", "values": lob_matches}
    return defaults


def _normalise_story_scope_defaults(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
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
        values = _unique(
            re.sub(r"\s+", " ", str(v or "")).strip()
            for v in (value.get("values") or [])
            if str(v or "").strip()
        )
        return {"mode": mode, "values": values}

    return {
        "lob_scope": _norm_scope(raw.get("lob_scope")),
        "stage_scope": _norm_scope(raw.get("stage_scope")),
    }


def _normalise_signal_list(raw: Any, valid: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    values = []
    for item in raw:
        text = _norm_text(item).replace("-", "_")
        if text in valid:
            values.append(text)
    return _unique(values)


def _story_blob(story: JiraStory) -> str:
    return "\n".join(
        part for part in (
            story.summary,
            story.description,
            story.story_description,
            story.new_process,
            story.current_process,
            story.business_scenarios,
            story.impacted_areas,
            story.key_ui_steps,
            story.acceptance_criteria,
        )
        if part and part.strip()
    ).lower()


def _detect_entities(blob: str) -> list[str]:
    found = []
    lowered = (blob or "").lower()
    for canonical, phrases in _ENTITY_PATTERNS:
        if any(phrase in lowered for phrase in phrases):
            found.append(canonical)
    return _unique(found)


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for rule in rules:
        key = "::".join(
            _norm_text(rule.get(field))
            for field in ("condition", "target", "effect", "polarity", "family_hint")
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(rule)
    return out


def _condition_signature(text: Any) -> str:
    words = [word for word in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(word) > 2]
    return "_".join(words[:8])


def _clean_sentence(text: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" .-*\t")
    return cleaned


def _norm_text(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")


def _unique(values) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        if not value:
            continue
        key = str(value).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out

