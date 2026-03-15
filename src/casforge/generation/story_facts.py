from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from casforge.generation.heuristic_config import load_domain_knowledge
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

def _domain_knowledge() -> dict[str, Any]:
    return load_domain_knowledge()


def _lob_scope_hints() -> tuple[tuple[str, tuple[str, ...]], ...]:
    hints = []
    for canonical, phrases in _domain_knowledge().get("lob_aliases", {}).items():
        hints.append((canonical, tuple(phrases)))
    return tuple(hints)


def _entity_patterns() -> tuple[tuple[str, tuple[str, ...]], ...]:
    patterns = []
    for entry in _domain_knowledge().get("entities", ()):
        canonical = str(entry.get("canonical", "")).strip()
        aliases = tuple(entry.get("aliases") or ())
        if canonical and aliases:
            patterns.append((canonical, aliases))
    return tuple(patterns)


def _family_term_patterns() -> tuple[tuple[str, tuple[str, ...]], ...]:
    patterns = []
    for key, terms in _domain_knowledge().get("families", {}).items():
        patterns.append((key, tuple(terms)))
    return tuple(patterns)


def _matrix_patterns() -> tuple[tuple[str, tuple[str, ...]], ...]:
    patterns = []
    for key, terms in _domain_knowledge().get("matrix_terms", {}).items():
        patterns.append((key, tuple(terms)))
    return tuple(patterns)


def _stage_aliases() -> tuple[dict[str, Any], ...]:
    return tuple(_domain_knowledge().get("stages", ()))


def _state_transition_terms() -> tuple[str, ...]:
    return tuple(_domain_knowledge().get("state_transition_terms", ()))


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
            comments_block=_block("Comments / Final Approach Notes", story.supplemental_comments, 900),
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
    rules: list[dict[str, Any]] = []
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


def _rule_is_noise(rule: dict[str, Any]) -> bool:
    target = str(rule.get("target", "")).strip().lower()
    condition = str(rule.get("condition", "")).strip().lower()
    effect = str(rule.get("effect", "")).strip().lower()
    if _target_effect_is_ambiguous(target, effect):
        return True
    if target in {"this field", "application", "omni loan"}:
        return True
    if target == "sub loan" and effect == "display":
        return True
    if condition.startswith("where separate") and effect == "display":
        return True
    return False


def _target_effect_is_ambiguous(target: str, effect: str) -> bool:
    target = str(target or "").strip().lower()
    effect = str(effect or "").strip().lower()
    if target == "product type decision list":
        return True
    if target in {"application stage movement", "mtns"} and effect == "state_move":
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
    blob = _story_blob(story)
    data = raw if isinstance(raw, dict) else {}
    result = {
        "story_scope_defaults": _normalise_story_scope_defaults(data.get("story_scope_defaults")) or defaults,
        "entities": _normalise_entities(data.get("entities")),
        "rules": _normalise_rules(data.get("rules"), story, defaults),
        "coverage_signals": _normalise_signal_list(data.get("coverage_signals"), _VALID_COVERAGE_SIGNALS),
        "matrix_signals": _normalise_signal_list(data.get("matrix_signals"), _VALID_MATRIX_SIGNALS),
    }

    if not result["entities"]:
        result["entities"] = _detect_entities(blob)
    if not result["coverage_signals"]:
        result["coverage_signals"] = _detect_coverage_signals(blob, result["rules"])
    else:
        result["coverage_signals"] = _prune_coverage_signals(blob, result["rules"], result["coverage_signals"])
    if not result["matrix_signals"]:
        result["matrix_signals"] = _detect_matrix_signals(blob, result["rules"])
    else:
        result["matrix_signals"] = _prune_matrix_signals(blob, result["rules"], result["matrix_signals"])
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
        if existing and existing != polarity and key[2]:
            # Only prune when both rules share the same non-empty condition.
            # Empty-condition dual-polarity rules (e.g. "recommended" vs "not_recommended"
            # for the same target) are intentional complementary coverage — keep both.
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


_GENERIC_TARGETS = frozenset({
    "field", "amount", "limit", "rate", "value", "item", "option", "section",
    "button", "link", "screen", "page", "form", "panel", "tab",
})


def _target_is_specific(target: str) -> bool:
    """Return True when target is not a single generic word."""
    t = _norm_text(target or "")
    if not t:
        return False
    # A target with 2+ meaningful words is always specific enough.
    words = [w for w in t.split() if len(w) >= 3]
    if len(words) >= 2:
        return True
    # Single-word targets are specific only when not in the generic blocklist.
    return t not in _GENERIC_TARGETS


def _heuristic_facts_are_authoritative(facts: dict[str, Any]) -> bool:
    rules = list(facts.get("rules") or [])
    if not rules:
        return False

    # If any two rules share (target, effect) but disagree on polarity the heuristic
    # is internally contradictory — the LLM must resolve the ambiguity.
    polarity_seen: dict[tuple[str, str], str] = {}
    for rule in rules:
        key = (_norm_text(rule.get("target")), _norm_text(rule.get("effect")))
        polarity = _norm_text(rule.get("polarity"))
        if key[0] and key[1] and polarity:
            existing = polarity_seen.get(key)
            if existing and existing != polarity:
                return False
            polarity_seen[key] = polarity

    # Require at least 2 rules with specific (non-generic) targets.
    # Generic targets like "field", "amount", "limit" indicate heuristic
    # fired on financial-value sentences rather than structured UI rules.
    specific = [r for r in rules if _target_is_specific(r.get("target", ""))]
    if len(specific) < 2:
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
    if len(rules) >= 5 and len(families) >= 3 and len(coverage) >= 3 and len(entities) >= 2:
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
    for canonical, phrases in _entity_patterns():
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
            target = _infer_target_from_text(" ".join(part for part in (condition, target) if part), story=story)
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
    if effect == "display":
        if re.search(r"\bnot\b.*?\b(?:display|visible|show|shown)\b|\bhide\b|\bhidden\b", blob):
            return "negative"
        return "positive"
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
        return "zero_not_allowed" if re.search(r"not(?:\s+be)?\s+allow|prevent|error|invalid|reject", blob) else "zero_allowed"
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
    blob = " ".join(part for part in fallback_parts if part).lower()
    if text in _VALID_FAMILIES and not _family_conflicts_with_effect(text, effect, blob):
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
    if re.search(r"mandatory|required|validation|invalid|error|zero", blob):
        return "validation"
    if re.search(r"if any|if all|based on|same as|derived", blob):
        return "dependency"
    if _looks_like_state_movement(blob):
        return "state_movement"
    if re.search(r"save|reopen|retain|persist", blob):
        return "persistence"
    if re.search(r"duplicate|blank|null|edge|mixed|tie", blob):
        return "edge"
    return "positive" if blob else None


def _detect_coverage_signals(blob: str, rules: list[dict[str, Any]]) -> list[str]:
    text = (blob or "").lower()
    signals: list[str] = []
    for signal, phrases in _family_term_patterns():
        if signal == "default_state":
            continue
        if signal in _VALID_COVERAGE_SIGNALS and any(phrase in text for phrase in phrases):
            signals.append(signal)
    if _looks_like_default_state_signal(text):
        signals.append("default_state")
    if _looks_like_validation_signal(text):
        signals.append("validation")
    if _looks_like_edge_signal(text):
        signals.append("edge")
    if _looks_like_state_movement(text):
        signals.append("state_movement")
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
    for signal, phrases in _matrix_patterns():
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


def _prune_coverage_signals(blob: str, rules: list[dict[str, Any]], signals: list[str]) -> list[str]:
    supported = set(_detect_coverage_signals(blob, rules))
    return [signal for signal in signals if signal in supported]


def _prune_matrix_signals(blob: str, rules: list[dict[str, Any]], signals: list[str]) -> list[str]:
    supported = set(_detect_matrix_signals(blob, rules))
    return [signal for signal in signals if signal in supported]


def _candidate_rule_sentences(story: JiraStory) -> list[str]:
    lines: list[str] = []
    for block in (story.new_process, story.business_scenarios, story.acceptance_criteria, story.story_description, story.supplemental_comments, story.description):
        if not block:
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip(" -*\t")
            if not line:
                continue
            pieces = re.split(r"(?<=[.;])\s+|\s+\*\s+", line)
            for piece in pieces:
                for cleaned in _split_rule_clause(piece):
                    if cleaned:
                        lines.append(cleaned)
    return _unique(lines)


# Words that signal a clause makes an independent state/effect claim.
# Used to detect "display and enable" style compound sentences.
_CLAUSE_EFFECT_KEYWORDS: frozenset = frozenset({
    "displayed", "display", "visible", "shown",
    "enabled", "editable",
    "disabled", "readonly",
    "checked", "unchecked",
    "derived", "calculated",
    "mandatory", "required",
    "saved", "retained",
})

_CONDITION_MARKERS: tuple = ("if ", "when ", "where ", "once ", "after ")


def _clause_has_independent_effect(part: str) -> bool:
    tokens = set(re.findall(r"[a-z]+", part.lower()))
    return bool(tokens & _CLAUSE_EFFECT_KEYWORDS)


def _attach_condition_to_headless_parts(original: str, parts: list[str]) -> list[str]:
    """Re-attach the leading condition from the original sentence to any split part
    that has lost it (e.g. the second part of 'if X, A should be Y and B should be Z')."""
    original_lower = original.lower()
    condition_prefix: Optional[str] = None
    for marker in _CONDITION_MARKERS:
        idx = original_lower.find(marker)
        if idx < 0:
            continue
        cond_text = original[idx:]
        for sep in (", ", "; ", " then "):
            sep_idx = cond_text.lower().find(sep)
            if sep_idx > 0:
                condition_prefix = _clean_sentence(cond_text[:sep_idx])
                break
        if condition_prefix:
            break
    if not condition_prefix:
        return parts
    out = []
    for part in parts:
        part_lower = part.lower()
        has_marker = any(marker in part_lower for marker in _CONDITION_MARKERS)
        if not has_marker and condition_prefix.lower() not in part_lower:
            out.append(f"{condition_prefix}, {part}")
        else:
            out.append(part)
    return out


def _split_rule_clause(piece: str) -> list[str]:
    cleaned = _clean_sentence(piece)
    if not cleaned:
        return []
    if " and " not in cleaned.lower():
        return [cleaned]
    parts = [_clean_sentence(part) for part in re.split(r"\band\b", cleaned, flags=re.I)]
    parts = [part for part in parts if part and len(re.findall(r"[a-z0-9]+", part.lower())) >= 3]
    if len(parts) < 2:
        return [cleaned]
    # Split when any part contains state-movement language (original behaviour).
    # Do NOT propagate conditions here — condition prefixes introduce entity terms
    # (e.g. "subloan") that shadow the stage target in _infer_target_from_text.
    if any(_looks_like_state_movement(part.lower()) for part in parts):
        return parts
    # Also split when exactly two parts each independently carry an effect signal
    # (e.g. "X should be displayed and Y should be enabled").
    # Limit to 2-part splits to avoid over-fragmenting long enumeration clauses.
    if len(parts) == 2 and all(_clause_has_independent_effect(part) for part in parts):
        return _attach_condition_to_headless_parts(cleaned, parts)
    return [cleaned]


def _heuristic_rule(sentence: str, defaults: dict[str, Any], story: JiraStory) -> Optional[dict[str, Any]]:
    text = _clean_sentence(sentence)
    if not text:
        return None
    lowered = text.lower()
    if len(re.findall(r"[a-z0-9]+", lowered)) < 4:
        return None
    if not any(token in lowered for token in (
        "decision", "checkbox", "column", "field", "stage", "grid", "save", "retain", "persist",
        "recommended", "vote", "verdict", "enable", "disable", "mandatory", "zero", "move",
        "display", "shown", "visible", "section",
    )):
        return None
    # Skip positional placement sentences — the mentioned field is a spatial anchor,
    # not the rule target (e.g. "checkbox added before recommended amount field").
    if re.search(r"\b(?:add(?:ed)?|place[d]?|insert(?:ed)?|position\w*)\b.{0,25}\bbefore\b", lowered):
        return None

    target = _infer_target_from_text(text, defaults, story)
    effect = _infer_effect(text)
    polarity = _normalise_polarity(None, effect, text)
    family = _normalise_family(None, effect, polarity, text)
    if effect == "state_move" and (not target or not str(target).lower().endswith("stage")):
        return None
    if not target or not effect or not family or _target_effect_is_ambiguous(target, effect):
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


def _story_control_target(story: Optional[JiraStory], control_kind: str, text: str = "") -> Optional[str]:
    generic = _generic_control_target(control_kind)
    if not story:
        return generic
    candidates = [
        entity for entity in _detect_entities(_story_blob(story))
        if control_kind in entity.lower()
    ]
    if len(candidates) == 1:
        return candidates[0]
    text_tokens = _text_tokens(text)
    matched = [
        entity for entity in candidates
        if _entity_specific_tokens(entity, control_kind) & text_tokens
    ]
    if len(matched) == 1:
        return matched[0]
    if not matched:
        return generic
    ranked = sorted(candidates, key=_entity_specificity, reverse=True)
    return ranked[0] if ranked else generic


def _generic_control_target(control_kind: str) -> Optional[str]:
    candidates = [
        canonical for canonical, _phrases in _entity_patterns()
        if control_kind in canonical.lower()
    ]
    ranked = sorted(candidates, key=_entity_specificity)
    return ranked[0] if ranked else None


def _entity_specificity(entity: str) -> tuple[int, int]:
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(entity).lower()) if len(token) > 2]
    return (len(tokens), sum(len(token) for token in tokens))


def _entity_specific_tokens(entity: str, control_kind: str) -> set[str]:
    generic = {
        control_kind,
        "decision",
        "grid",
        "field",
        "column",
        "dropdown",
        "screen",
        "list",
    }
    return {token for token in _text_tokens(entity) if token not in generic}


def _text_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(text).lower()) if len(token) > 2}


def _normalise_plural_control(text: str) -> str:
    normalised = str(text or "").strip()
    normalised = re.sub(r"\bcheckboxes\b", "checkbox", normalised)
    normalised = re.sub(r"\bcolumns\b", "column", normalised)
    normalised = re.sub(r"\bfields\b", "field", normalised)
    return normalised


def _stage_target_from_text(text: str) -> Optional[str]:
    lowered = str(text or "").lower()
    for entry in _stage_aliases():
        canonical = str(entry.get("canonical", "")).strip()
        aliases = entry.get("aliases") or ()
        if canonical and any(alias in lowered for alias in aliases):
            return f"{canonical.lower()} stage"
    return None


def _infer_target_from_text(
    text: str,
    defaults: Optional[dict[str, Any]] = None,
    story: Optional[JiraStory] = None,
) -> Optional[str]:
    lowered = text.lower()
    for canonical, phrases in _entity_patterns():
        if any(phrase in lowered for phrase in phrases):
            return canonical
    if re.search(r"\bcheckbox(?:es)?\b|\bcheck box(?:es)?\b", lowered):
        story_target = _story_control_target(story, "checkbox", lowered)
        if story_target:
            return story_target
    direct_patterns = (
        r"([a-z][a-z0-9 /'-]{2,40}? field)",
        r"([a-z][a-z0-9 /'-]{2,40}? column)",
        r"([a-z][a-z0-9 /'-]{2,40}? checkbox(?:es)?)",
        r"([a-z][a-z0-9 /'-]{2,40}? verdict)",
        r"([a-z][a-z0-9 /'-]{2,40}? section)",
    )
    for pattern in direct_patterns:
        match = re.search(pattern, lowered)
        if match:
            return _normalise_plural_control(match.group(1).strip())
    stage_target = _stage_target_from_text(lowered)
    if stage_target and _looks_like_state_movement(lowered):
        return stage_target
    return None


def _infer_effect(text: str) -> Optional[str]:
    lowered = text.lower()
    if re.search(r"\bdisabled?\b|read ?only|not editable", lowered):
        return "disable"
    if re.search(r"\benabled?\b|editable", lowered):
        return "enable"
    if re.search(r"selected as|updated to|set to", lowered) and re.search(r"recommended|not recommended|approved|rejected", lowered):
        return "derive"
    if "by default" in lowered or "default" in lowered and ("checked" in lowered or "unchecked" in lowered):
        return "default_state"
    if re.search(r"\bdisplay(?:ed)?\b|\bvisible\b|\bshown?\b|new column|column", lowered):
        return "display"
    if re.search(r"\bderive\b|\bderived\b|\bcalculated\b|same as", lowered):
        return "derive"
    if _looks_like_state_movement(lowered):
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


def _looks_like_state_movement(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    if "next stage" in lowered or "move next" in lowered or "move to next stage" in lowered or "mtns" in lowered:
        return True
    has_transition_verb = bool(re.search(r"\bmove\b|\bmoved\b|\btransition\b|\btransitions\b|\bproceed\b|\bproceeds\b|\bgo\b|\bgoes\b", lowered))
    has_stage_target = any(term in lowered for term in _state_transition_terms())
    return has_transition_verb and has_stage_target


def _looks_like_default_state_signal(text: str) -> bool:
    lowered = (text or "").lower()
    has_default = bool(re.search(r"\bby default\b|\bdefault\b", lowered))
    has_state = bool(re.search(r"\bchecked?\b|\bunchecked\b|\bselected\b|\benabled?\b|\bdisabled?\b", lowered))
    return has_default and has_state


def _looks_like_validation_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return bool(re.search(r"mandatory|required|validation|invalid|error|duplicate|blank|null|zero|not allow|must not|cannot|can't", lowered))


def _looks_like_edge_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return bool(re.search(r"\bzero\b|\bblank\b|\bnull\b|\bduplicate\b|\bempty\b", lowered))


def _family_conflicts_with_effect(family: str, effect: Optional[str], blob: str) -> bool:
    family = str(family or "").strip().lower()
    effect = str(effect or "").strip().lower()
    if family == "validation" and effect not in {"validate", "zero_validation"} and not _looks_like_validation_signal(blob):
        return True
    if family == "positive" and effect in {"enable", "disable", "derive", "selection_dependency", "state_move"}:
        return True
    return False


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
    stage_target = _stage_target_from_text(text)
    if stage_target:
        return _normalize_stage_target(stage_target)
    return None


def _extract_lob_scope(text: str) -> Optional[str]:
    lowered = text.lower()
    for canonical, phrases in _lob_scope_hints():
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


def _normalize_stage_target(target: str) -> str:
    cleaned = re.sub(r"\bstage\b", "", str(target or ""), flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip().title()


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
    for canonical, phrases in _lob_scope_hints():
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
    for canonical, phrases in _entity_patterns():
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

