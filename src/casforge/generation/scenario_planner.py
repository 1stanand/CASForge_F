from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from casforge.generation.heuristic_config import load_domain_knowledge, load_planner_hints
from casforge.generation.story_facts import extract_story_facts, infer_story_facts_heuristically
from casforge.parsing.jira_parser import JiraStory

_FAMILY_ORDER = {
    "positive": 0,
    "validation": 1,
    "negative": 2,
    "dependency": 3,
    "state_movement": 4,
    "persistence": 5,
    "data_combination": 6,
    "edge": 7,
}

_EFFECT_TO_OUTCOME = {
    "display": "display",
    "enable": "enabled",
    "disable": "disabled",
    "derive": "derived_value",
    "validate": "validation_error",
    "default_state": "checked",
    "state_move": "state_change",
    "persistence": "persistence",
    "zero_validation": "validation_error",
    "selection_dependency": "derived_value",
}

_POLARITY_TO_FORBIDDEN = {
    "enabled": ["disabled", "readonly", "read only"],
    "disabled": ["enabled", "editable"],
    "checked": ["unchecked", "disabled"],
    "unchecked": ["checked", "selected"],
    "recommended": ["not recommended", "rejected"],
    "not_recommended": ["recommended"],
    "zero_allowed": ["error", "reject", "invalid"],
    "zero_not_allowed": ["allowed", "accepted"],
}

def _domain_knowledge() -> dict[str, Any]:
    return load_domain_knowledge()


def _planner_hints() -> dict[str, Any]:
    return load_planner_hints()


def _section_specs() -> dict[str, dict[str, Any]]:
    return _domain_knowledge().get("sections", {})


def _section_spec(key: str) -> dict[str, Any]:
    spec = _section_specs().get(key, {})
    display_name = str(spec.get("display_name") or _normalize_visible_text(key.replace("_", " "))).strip()
    terms = tuple(spec.get("terms") or ())
    return {"display_name": display_name, "terms": terms}


def _matrix_hint_terms() -> dict[str, tuple[str, ...]]:
    return _domain_knowledge().get("matrix_terms", {})


def _target_aliases() -> tuple[dict[str, Any], ...]:
    return tuple(_planner_hints().get("target_aliases", ()))


def _synthetic_entity_blocklist() -> set[str]:
    return set(_planner_hints().get("synthetic_entity_blocklist", set()))


def _synthetic_templates() -> dict[str, tuple[str, ...]]:
    return _planner_hints().get("synthetic_templates", {})


def build_scenario_plan_items(
    story: JiraStory,
    story_scope_defaults: Optional[dict[str, Any]] = None,
    story_facts: Optional[dict[str, Any]] = None,
    intents: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    defaults = _normalise_story_scope_defaults(story_scope_defaults)
    facts = story_facts or (infer_story_facts_heuristically(story, defaults) if intents else extract_story_facts(story, defaults))
    default_screen = _infer_default_screen_hint(story)

    if intents:
        plan_items = [
            _enrich_existing_intent(item, idx, story, facts, defaults, default_screen)
            for idx, item in enumerate(intents, 1)
        ]
    else:
        plan_items = _plan_items_from_facts(story, facts, defaults, default_screen)

    deduped = _dedupe_plan_items(plan_items)
    return sorted(deduped, key=lambda item: (_FAMILY_ORDER.get(item.get("family", "positive"), 99), item.get("text", "").lower()))


def public_intent_records(plan_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in plan_items:
        record = {
            "id": item.get("id"),
            "text": item.get("text"),
            "family": item.get("family", "positive"),
            "inherit_story_scope": bool(item.get("inherit_story_scope", True)),
            "lob_scope": item.get("lob_scope"),
            "stage_scope": item.get("stage_scope"),
            "action_target": item.get("action_target"),
            "screen_hint": item.get("screen_hint"),
            "expected_outcome": item.get("expected_outcome"),
            "entity": item.get("entity"),
            "target_field": item.get("target_field"),
            "expected_state": item.get("expected_state"),
            "polarity": item.get("polarity"),
            "must_anchor_terms": list(item.get("must_anchor_terms") or []),
            "must_assert_terms": list(item.get("must_assert_terms") or []),
            "forbidden_terms": list(item.get("forbidden_terms") or []),
            "matrix_signature": item.get("matrix_signature"),
            "allow_expansion": bool(item.get("allow_expansion", False)),
            "section_key": item.get("section_key"),
            "section_title": item.get("section_title"),
            "pattern_terms": list(item.get("pattern_terms") or []),
        }
        records.append(record)
    return records


def _plan_items_from_facts(
    story: JiraStory,
    facts: dict[str, Any],
    defaults: dict[str, Any],
    default_screen: Optional[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    rules = list(facts.get("rules") or [])
    for idx, rule in enumerate(rules, 1):
        item = _plan_item_from_rule(rule, idx, facts, defaults, default_screen)
        if item:
            items.append(item)

    coverage_signals = list(facts.get("coverage_signals") or [])
    if not items:
        items.extend(_synthetic_items_from_signals(story, facts, defaults, default_screen, start_index=1))
    elif len(items) < 6:
        extras = _synthetic_items_from_signals(story, facts, defaults, default_screen, start_index=len(items) + 1)
        items.extend(_uncovered_family_items(items, extras))

    if len(items) < 5 and coverage_signals:
        extras = _synthetic_items_from_signals(story, facts, defaults, default_screen, start_index=len(items) + 1, fill_shortfall=True)
        items.extend(_uncovered_family_items(items, extras))
    return items


def _uncovered_family_items(existing: list[dict[str, Any]], extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    covered = {item.get("family") for item in existing if item.get("family")}
    out: list[dict[str, Any]] = []
    for extra in extras:
        family = extra.get("family")
        if not family or family in covered:
            continue
        covered.add(family)
        out.append(extra)
    return out


def _plan_item_from_rule(
    rule: dict[str, Any],
    idx: int,
    facts: dict[str, Any],
    defaults: dict[str, Any],
    default_screen: Optional[str],
) -> Optional[dict[str, Any]]:
    raw_target = str(rule.get("target") or "").strip()
    effect = str(rule.get("effect") or "").strip()
    family = str(rule.get("family_hint") or "positive").strip()
    condition = str(rule.get("condition") or "").strip()
    polarity = str(rule.get("polarity") or "positive").strip()
    if not raw_target or not effect:
        return None

    scope = _scope_for_rule(rule, defaults)
    target = _canonical_plan_target(raw_target, condition, effect, scope)
    screen_hint = _screen_hint_for_rule(rule, target, scope, default_screen)
    target_field = target
    expected_state = _expected_state_for_rule(effect, polarity, target, condition)
    action_target = _action_target_for_rule(effect, target)
    matrix_signature = _matrix_signature(rule, facts, condition, target)
    section_key, section_title = _section_for_plan(
        target=target,
        effect=effect,
        polarity=polarity,
        family=family,
        matrix_signature=matrix_signature,
        screen_hint=screen_hint,
    )
    pattern_terms = _pattern_terms_for_plan(section_key, target, effect, matrix_signature, screen_hint)

    text = _title_from_rule(target, effect, polarity, condition, scope)
    must_anchor_terms = _keyword_terms([action_target, target, screen_hint, condition])
    must_assert_terms = _keyword_terms([expected_state, effect, polarity, target])
    forbidden_terms = _forbidden_terms(polarity, expected_state)

    if _is_low_information_title(text):
        return None

    return {
        "id": f"intent_{idx:03d}",
        "text": text,
        "title": text,
        "family": family,
        "inherit_story_scope": not (_is_specific_scope(scope.get("lob_scope")) or _is_specific_scope(scope.get("stage_scope"))),
        "lob_scope": scope.get("lob_scope") if _is_specific_scope(scope.get("lob_scope")) else None,
        "stage_scope": scope.get("stage_scope") if _is_specific_scope(scope.get("stage_scope")) else None,
        "action_target": action_target,
        "screen_hint": screen_hint,
        "expected_outcome": _EFFECT_TO_OUTCOME.get(effect, expected_state),
        "entity": _best_entity(target, facts),
        "target_field": target_field,
        "expected_state": expected_state,
        "polarity": polarity,
        "must_anchor_terms": must_anchor_terms,
        "must_assert_terms": must_assert_terms,
        "forbidden_terms": forbidden_terms,
        "matrix_signature": matrix_signature,
        "allow_expansion": matrix_signature not in {"base", ""},
        "section_key": section_key,
        "section_title": section_title,
        "pattern_terms": pattern_terms,
        "source_rule": rule,
    }


def _synthetic_items_from_signals(
    story: JiraStory,
    facts: dict[str, Any],
    defaults: dict[str, Any],
    default_screen: Optional[str],
    start_index: int,
    fill_shortfall: bool = False,
) -> list[dict[str, Any]]:
    primary_entity = _best_entity_from_facts(facts) or "business behavior"
    if not _synthetic_entity_specific_enough(primary_entity):
        return []
    signals = list(facts.get("coverage_signals") or [])
    matrix_signals = list(facts.get("matrix_signals") or [])
    synthetic_specs = []

    if "ui_structure" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_visibility", primary_entity, "positive", "display", "positive"))
    if "default_state" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_default_state", primary_entity, "positive", "default_state", "checked"))
    if "field_enablement" in signals or "dependency" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_enablement", primary_entity, "dependency", "enable", "enabled"))
    if "derived_decision" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_derivation", primary_entity, "dependency", "derive", "derived"))
    if "validation" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_validation", primary_entity, "validation", "validate", "negative"))
    if "state_movement" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_transition", primary_entity, "state_movement", "state_move", "moved"))
    if "persistence" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_persistence", primary_entity, "persistence", "persistence", "retained"))
    if "data_combination" in signals or matrix_signals:
        synthetic_specs.extend(_synthetic_specs("generic_combination", primary_entity, "data_combination", "selection_dependency", "positive"))
    if "edge" in signals:
        synthetic_specs.extend(_synthetic_specs("generic_edge", primary_entity, "edge", "validate", "negative"))

    if fill_shortfall and not synthetic_specs:
        synthetic_specs.extend(_synthetic_specs("generic_visibility", primary_entity, "positive", "display", "positive"))
        synthetic_specs.extend(_synthetic_specs("generic_validation", primary_entity, "validation", "validate", "negative"))

    items = []
    seen = set()
    for offset, (family, text, effect, polarity) in enumerate(synthetic_specs, start_index):
        normalized_text = _normalize_visible_text(text)
        if normalized_text.lower() in seen or _is_low_information_title(normalized_text):
            continue
        seen.add(normalized_text.lower())
        matrix_signature = _matrix_signature({"target": primary_entity}, facts, normalized_text, primary_entity)
        section_key, section_title = _section_for_plan(
            target=primary_entity,
            effect=effect,
            polarity=polarity,
            family=family,
            matrix_signature=matrix_signature,
            screen_hint=default_screen,
        )
        items.append({
            "id": f"intent_{offset:03d}",
            "text": normalized_text,
            "title": normalized_text,
            "family": family,
            "inherit_story_scope": True,
            "lob_scope": None,
            "stage_scope": None,
            "action_target": primary_entity,
            "screen_hint": default_screen,
            "expected_outcome": _EFFECT_TO_OUTCOME.get(effect, polarity),
            "entity": primary_entity,
            "target_field": primary_entity,
            "expected_state": _expected_state_for_rule(effect, polarity, primary_entity, normalized_text),
            "polarity": polarity,
            "must_anchor_terms": _keyword_terms([primary_entity, default_screen, normalized_text]),
            "must_assert_terms": _keyword_terms([effect, polarity, primary_entity]),
            "forbidden_terms": _forbidden_terms(polarity, None),
            "matrix_signature": matrix_signature,
            "allow_expansion": bool(matrix_signals),
            "section_key": section_key,
            "section_title": section_title,
            "pattern_terms": _pattern_terms_for_plan(section_key, primary_entity, effect, matrix_signature, default_screen),
        })
    return items


def _synthetic_specs(
    template_key: str,
    target: str,
    family: str,
    effect: str,
    polarity: str,
) -> list[tuple[str, str, str, str]]:
    templates = _synthetic_templates().get(template_key, ())
    out: list[tuple[str, str, str, str]] = []
    for template in templates:
        rendered = _normalize_visible_text(template.format(target=target))
        if rendered:
            out.append((family, rendered, effect, polarity))
    return out


def _enrich_existing_intent(
    item: dict[str, Any],
    idx: int,
    story: JiraStory,
    facts: dict[str, Any],
    defaults: dict[str, Any],
    default_screen: Optional[str],
) -> dict[str, Any]:
    text = _normalize_visible_text(item.get("text") or item.get("title") or "")
    matched_rule = _best_matching_rule(text, facts.get("rules") or [])

    family = str(item.get("family") or matched_rule.get("family_hint") or "positive").strip()
    entity = str(item.get("entity") or matched_rule.get("target") or _infer_entity_from_text(text, facts) or "").strip() or None
    target_field = str(item.get("target_field") or matched_rule.get("target") or entity or item.get("action_target") or "").strip() or None
    polarity = str(item.get("polarity") or matched_rule.get("polarity") or _infer_polarity_from_text(text) or "positive").strip()
    effect = str((matched_rule or {}).get("effect") or _effect_from_intent_text(text) or "display")
    expected_state = str(item.get("expected_state") or _expected_state_for_rule(effect, polarity, target_field or entity or text, text)).strip()
    action_target = str(item.get("action_target") or _action_target_for_rule(effect, target_field or entity or text)).strip() or None
    screen_hint = str(item.get("screen_hint") or (matched_rule or {}).get("screen_hint") or default_screen or "").strip() or None

    scope = _scope_for_intent_item(item, matched_rule, defaults)
    must_anchor_terms = _ensure_terms(item.get("must_anchor_terms"), [action_target, target_field, entity, screen_hint, text])
    must_assert_terms = _ensure_terms(item.get("must_assert_terms"), [item.get("expected_outcome"), expected_state, polarity, target_field, text])
    forbidden_terms = _ensure_terms(item.get("forbidden_terms"), _forbidden_terms(polarity, expected_state))
    matrix_signature = str(item.get("matrix_signature") or _matrix_signature(matched_rule or {}, facts, text, target_field or entity or text)).strip() or "base"
    section_key, section_title = _section_for_plan(
        target=target_field or entity or text,
        effect=effect,
        polarity=polarity,
        family=family,
        matrix_signature=matrix_signature,
        screen_hint=screen_hint,
    )
    pattern_terms = _ensure_terms(
        item.get("pattern_terms"),
        _pattern_terms_for_plan(section_key, target_field or entity or text, effect, matrix_signature, screen_hint),
    )

    enriched = {
        "id": item.get("id") or f"intent_{idx:03d}",
        "text": text,
        "title": text,
        "family": family,
        "inherit_story_scope": bool(item.get("inherit_story_scope", True)),
        "lob_scope": item.get("lob_scope"),
        "stage_scope": item.get("stage_scope"),
        "action_target": action_target,
        "screen_hint": screen_hint,
        "expected_outcome": item.get("expected_outcome") or _EFFECT_TO_OUTCOME.get(effect, expected_state),
        "entity": entity,
        "target_field": target_field,
        "expected_state": expected_state,
        "polarity": polarity,
        "must_anchor_terms": must_anchor_terms,
        "must_assert_terms": must_assert_terms,
        "forbidden_terms": forbidden_terms,
        "matrix_signature": matrix_signature,
        "allow_expansion": bool(item.get("allow_expansion", matrix_signature not in {"", "base"})),
        "section_key": item.get("section_key") or section_key,
        "section_title": item.get("section_title") or section_title,
        "pattern_terms": pattern_terms,
        "source_rule": matched_rule or None,
    }

    if not enriched["lob_scope"] and _is_specific_scope(scope.get("lob_scope")):
        enriched["lob_scope"] = scope.get("lob_scope")
        enriched["inherit_story_scope"] = False
    if not enriched["stage_scope"] and _is_specific_scope(scope.get("stage_scope")):
        enriched["stage_scope"] = scope.get("stage_scope")
        enriched["inherit_story_scope"] = False
    return enriched


def _best_matching_rule(text: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    if not text or not rules:
        return {}
    best = {}
    best_score = 0.0
    for rule in rules:
        blob = " ".join(str(rule.get(key, "")) for key in ("condition", "target", "effect", "polarity", "family_hint", "screen_hint"))
        score = SequenceMatcher(None, text.lower(), blob.lower()).ratio()
        score += 0.25 * _token_overlap(text, blob)
        if score > best_score:
            best = rule
            best_score = score
    return best if best_score >= 0.18 else {}


def _scope_for_rule(rule: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "lob_scope": _normalise_scope(rule.get("lob_scope")) if rule.get("lob_scope") else defaults.get("lob_scope"),
        "stage_scope": _normalise_scope(rule.get("stage_scope")) if rule.get("stage_scope") else defaults.get("stage_scope"),
    }


def _scope_for_intent_item(item: dict[str, Any], matched_rule: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    if bool(item.get("inherit_story_scope", True)):
        lob = _normalise_scope(item.get("lob_scope"))
        stage = _normalise_scope(item.get("stage_scope"))
        return {
            "lob_scope": lob if _is_specific_scope(lob) else defaults.get("lob_scope"),
            "stage_scope": stage if _is_specific_scope(stage) else defaults.get("stage_scope"),
        }
    return {
        "lob_scope": _normalise_scope(item.get("lob_scope") or matched_rule.get("lob_scope") or defaults.get("lob_scope")),
        "stage_scope": _normalise_scope(item.get("stage_scope") or matched_rule.get("stage_scope") or defaults.get("stage_scope")),
    }


def _expected_state_for_rule(effect: str, polarity: str, target: str, condition: str) -> str:
    if effect == "display":
        return "display"
    if effect == "enable":
        return "enabled"
    if effect == "disable":
        return "disabled"
    if effect == "default_state":
        return "checked" if polarity != "unchecked" else "unchecked"
    if effect in {"derive", "selection_dependency"}:
        if polarity in {"recommended", "not_recommended"}:
            return polarity
        return "derived"
    if effect == "state_move":
        return "moved"
    if effect == "persistence":
        return "retained"
    if effect == "zero_validation":
        return "zero_not_allowed" if polarity == "zero_not_allowed" else "zero_allowed"
    if effect == "validate":
        return "validation_error" if polarity in {"negative", "not_allowed"} or re.search(r"mandatory|required|invalid|error|zero", condition.lower()) else "validated"
    return polarity or "positive"


def _action_target_for_rule(effect: str, target: str) -> str:
    if effect == "display":
        return target
    if effect in {"enable", "disable", "default_state", "validate", "zero_validation"}:
        return target
    if effect == "state_move":
        # Use the specific stage target directly (e.g., "credit approval stage")
        # to improve anchor retrieval specificity over the generic "move to next stage".
        return target
    return target


def _title_from_rule(target: str, effect: str, polarity: str, condition: str, scope: Optional[dict[str, Any]] = None) -> str:
    condition_hint = _condition_suffix(condition)
    title_target = _title_target(target, effect)
    if effect == "display":
        return _normalize_visible_text(f"Display {title_target}{condition_hint}")
    if effect == "default_state":
        state = "unchecked" if polarity == "unchecked" else "checked"
        return _normalize_visible_text(f"Keep {title_target} {state} by default{condition_hint}")
    if effect == "enable":
        return _normalize_visible_text(f"Enable {title_target}{condition_hint}")
    if effect == "disable":
        return _normalize_visible_text(f"Disable {title_target}{condition_hint}")
    if effect in {"derive", "selection_dependency"}:
        derived_state = _derived_state_phrase(polarity)
        if derived_state:
            return _normalize_visible_text(f"Set {title_target} to {derived_state}{condition_hint}")
        return _normalize_visible_text(f"Derive {title_target}{condition_hint}")
    if effect in {"validate", "zero_validation"}:
        if "zero" in condition.lower() or polarity.startswith("zero"):
            return _normalize_visible_text(f"Validate zero value for {title_target}{condition_hint}")
        return _normalize_visible_text(f"Validate {title_target}{condition_hint}")
    if effect == "state_move":
        return _normalize_visible_text(f"Move application to {title_target}{condition_hint}")
    if effect == "persistence":
        return _normalize_visible_text(f"Retain {title_target} after save and reopen")
    return _normalize_visible_text(f"Resolve {title_target}{condition_hint}")


def _title_target(target: str, effect: str) -> str:
    cleaned = _normalize_visible_text(target)
    if effect == "default_state" and cleaned.lower().endswith("checkbox"):
        return f"{cleaned}es"
    return cleaned


def _derived_state_phrase(polarity: str) -> Optional[str]:
    lowered = str(polarity or "").strip().lower()
    mapping = {
        "recommended": "Recommended",
        "not_recommended": "Not Recommended",
        "checked": "Checked",
        "unchecked": "Unchecked",
        "enabled": "Enabled",
        "disabled": "Disabled",
    }
    return mapping.get(lowered)


def _condition_suffix(condition: str) -> str:
    if not condition:
        return ""
    lower = condition.lower()
    for marker in ("if ", "when ", "after ", "once ", "on "):
        idx = lower.find(marker)
        if idx >= 0:
            suffix = condition[idx:]
            words = re.findall(r"[A-Za-z0-9']+", suffix)
            if len(words) > 8:
                suffix = " ".join(words[:8])
            return f" {suffix}"
    words = re.findall(r"[A-Za-z0-9']+", condition)
    if len(words) <= 8:
        return f" when {' '.join(words)}"
    return ""


def _canonical_plan_target(target: str, condition: str, effect: str, scope: Optional[dict[str, Any]]) -> str:
    lowered = target.lower()
    for entry in _target_aliases():
        if lowered == str(entry.get("match", "")).lower():
            return str(entry.get("canonical", "")).strip() or target
    return target


def _screen_hint_for_rule(rule: dict[str, Any], target: str, scope: Optional[dict[str, Any]], default_screen: Optional[str]) -> Optional[str]:
    explicit = str(rule.get("screen_hint") or "").strip()
    if explicit:
        return explicit
    return default_screen


def _scope_stage_value(scope: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(scope, dict):
        return None
    values = scope.get("values") or []
    return str(values[0]).strip() if values else None


def _best_entity(target: str, facts: dict[str, Any]) -> Optional[str]:
    entities = facts.get("entities") or []
    fallback = _target_entity_label(target)
    if not entities:
        return fallback or target or None
    ranked = sorted(
        entities,
        key=lambda entity: (
            _token_overlap(entity, target),
            _entity_rule_support(entity, facts),
            _entity_specificity_score(entity),
        ),
        reverse=True,
    )
    return ranked[0] if ranked and _token_overlap(ranked[0], target) > 0 else fallback or target or None


def _best_entity_from_facts(facts: dict[str, Any]) -> Optional[str]:
    entities = list(facts.get("entities") or [])
    if not entities:
        return None
    ranked = sorted(
        entities,
        key=lambda entity: (
            1 if _synthetic_entity_specific_enough(entity) else 0,
            _entity_rule_support(entity, facts),
            _entity_specificity_score(entity),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _infer_entity_from_text(text: str, facts: dict[str, Any]) -> Optional[str]:
    candidates = list(facts.get("entities") or [])
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda entity: _token_overlap(entity, text), reverse=True)
    if ranked and _token_overlap(ranked[0], text) > 0.10:
        return ranked[0]
    return None


def _effect_from_intent_text(text: str) -> Optional[str]:
    lowered = text.lower()
    if "disable" in lowered or "disabled" in lowered:
        return "disable"
    if "enable" in lowered or "enabled" in lowered:
        return "enable"
    if "default" in lowered or "checked" in lowered or "unchecked" in lowered:
        return "default_state"
    if "derive" in lowered or "same as" in lowered or "based on" in lowered:
        return "derive"
    if "validate" in lowered or "mandatory" in lowered or "error" in lowered or "zero" in lowered:
        return "validate"
    if "move" in lowered or "next stage" in lowered:
        return "state_move"
    if "retain" in lowered or "persist" in lowered or "reopen" in lowered:
        return "persistence"
    if "display" in lowered or "show" in lowered or "visible" in lowered:
        return "display"
    return None


def _infer_polarity_from_text(text: str) -> Optional[str]:
    lowered = text.lower()
    if "unchecked" in lowered:
        return "unchecked"
    if "checked" in lowered:
        return "checked"
    if "disabled" in lowered or "disable" in lowered or "read only" in lowered or "readonly" in lowered:
        return "disabled"
    if "enabled" in lowered or "enable" in lowered or "editable" in lowered:
        return "enabled"
    if "not recommended" in lowered:
        return "not_recommended"
    if "recommended" in lowered:
        return "recommended"
    if "zero" in lowered and ("error" in lowered or "not allow" in lowered or "invalid" in lowered):
        return "zero_not_allowed"
    if "reject" in lowered or "prevent" in lowered or "invalid" in lowered or "error" in lowered:
        return "negative"
    return None


def _matrix_signature(rule: dict[str, Any], facts: dict[str, Any], text: str, target: str) -> str:
    lowered = " ".join(str(part or "") for part in (rule.get("condition"), rule.get("target"), text, target)).lower()
    labels = []
    for signal, terms in _matrix_hint_terms().items():
        if any(term in lowered for term in terms):
            labels.append(signal)
    return "+".join(sorted(set(labels))) if labels else "base"


def _section_for_plan(
    target: str,
    effect: str,
    polarity: str,
    family: str,
    matrix_signature: str,
    screen_hint: Optional[str],
) -> tuple[str, str]:
    target_lower = (target or "").lower()
    matrix_labels = {label for label in (matrix_signature or "").split("+") if label and label != "base"}

    if effect == "display" and "column" in target_lower:
        return "ui_structure", _section_spec("ui_structure")["display_name"]
    if "checkbox" in target_lower and effect in {"display", "default_state"}:
        return "checkbox_state", _section_spec("checkbox_state")["display_name"]
    if effect in {"enable", "disable"} and any(term in target_lower for term in ("field", "limit", "amount")):
        return "field_enablement", _section_spec("field_enablement")["display_name"]
    if effect == "default_state":
        return "checkbox_state", _section_spec("checkbox_state")["display_name"]
    if any(term in target_lower for term in ("dropdown", "verdict")) or effect == "derive":
        return "decision_logic", _section_spec("decision_logic")["display_name"]
    if effect in {"validate", "zero_validation"} or family in {"validation", "negative"}:
        key = "edge" if ("zero" in target_lower or polarity.startswith("zero")) and family == "edge" else "validation"
        return key, _section_spec(key)["display_name"]
    if effect == "state_move" or family == "state_movement":
        return "state_movement", _section_spec("state_movement")["display_name"]
    if effect == "persistence" or family == "persistence":
        return "persistence", _section_spec("persistence")["display_name"]
    if family == "data_combination" and not any(term in target_lower for term in ("dropdown", "decision", "verdict")):
        return "data_combination", _section_spec("data_combination")["display_name"]
    if family == "dependency":
        if any(term in target_lower for term in ("limit", "amount", "field")):
            return "field_enablement", _section_spec("field_enablement")["display_name"]
        if any(term in matrix_labels for term in {"dependent_card", "any", "all", "none", "mixed"}) or "decision" in target_lower:
            return "dependency", _section_spec("dependency")["display_name"]
    return "core_flow", _section_spec("core_flow")["display_name"]


def _pattern_terms_for_plan(
    section_key: str,
    target: str,
    effect: str,
    matrix_signature: str,
    screen_hint: Optional[str],
) -> list[str]:
    terms = list(_section_spec(section_key).get("terms") or [])
    target_text = _normalize_visible_text(target)
    screen_text = _normalize_visible_text(screen_hint)
    if target_text:
        terms.append(target_text)
    if screen_text:
        terms.append(screen_text)
    if effect:
        terms.append(effect)
    for label in (matrix_signature or "").split("+"):
        if label and label != "base":
            terms.append(label.replace("_", " "))
    return _keyword_terms(terms)


def _forbidden_terms(polarity: Optional[str], expected_state: Optional[str]) -> list[str]:
    terms = []
    if polarity in _POLARITY_TO_FORBIDDEN:
        terms.extend(_POLARITY_TO_FORBIDDEN[polarity])
    if expected_state in _POLARITY_TO_FORBIDDEN:
        terms.extend(_POLARITY_TO_FORBIDDEN[expected_state])
    return _keyword_terms(terms)


def _ensure_terms(existing: Any, fallbacks: list[Any]) -> list[str]:
    if isinstance(existing, list) and existing:
        return _keyword_terms(existing)
    return _keyword_terms(fallbacks)


def _keyword_terms(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        text = _normalize_visible_text(value or "")
        if not text:
            continue
        if len(text.split()) <= 3:
            candidates = [text]
        else:
            candidates = []
            words = [word for word in re.findall(r"[A-Za-z0-9']+", text) if len(word) > 2]
            if words:
                candidates.append(" ".join(words[:3]))
            if len(words) >= 2:
                candidates.extend(words[:3])
        for candidate in candidates:
            lowered = candidate.lower()
            if lowered in seen or len(lowered) < 3:
                continue
            seen.add(lowered)
            out.append(candidate)
            if len(out) >= 6:
                return out
    return out


def _normalize_visible_text(text: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" .-")
    words = re.findall(r"[A-Za-z0-9']+", cleaned)
    if len(words) > 14:
        cleaned = " ".join(words[:14])
    return cleaned


def _target_entity_label(target: str) -> str:
    text = _normalize_visible_text(target).lower()
    replacements = (
        " for sub loan grid",
        " for credit card grid",
        " field",
        " dropdown",
        " column",
    )
    for suffix in replacements:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _entity_rule_support(entity: str, facts: dict[str, Any]) -> int:
    candidate = _normalize_visible_text(entity).lower()
    score = 0
    for rule in facts.get("rules") or []:
        target = str(rule.get("target") or "")
        condition = str(rule.get("condition") or "")
        score += int(_token_overlap(candidate, target) >= 0.34) * 2
        score += int(_token_overlap(candidate, condition) >= 0.34)
    return score


def _entity_specificity_score(entity: str) -> tuple[int, int]:
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(entity).lower()) if len(token) > 2]
    return (len(tokens), sum(len(token) for token in tokens))


def _synthetic_entity_specific_enough(entity: Optional[str]) -> bool:
    text = _normalize_visible_text(entity or "").lower()
    if not text or text in _synthetic_entity_blocklist():
        return False
    tokens = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 2}
    if tokens & {"checkbox", "column", "dropdown", "field", "amount", "limit", "verdict"}:
        return True
    if "decision" in tokens and "list" not in tokens:
        return True
    return False


def _token_overlap(a: str, b: str) -> float:
    ta = {token for token in re.findall(r"[a-z0-9]+", (a or "").lower()) if len(token) > 2}
    tb = {token for token in re.findall(r"[a-z0-9]+", (b or "").lower()) if len(token) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(min(len(ta), len(tb)), 1)


def _is_low_information_title(text: str) -> bool:
    lowered = text.lower()
    if not lowered or len(re.findall(r"[a-z0-9]+", lowered)) < 4:
        return True
    bad = ("system should", "should work", "as expected", "user logs in", "user navigates")
    return any(token in lowered for token in bad)


def _dedupe_plan_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    text_seen = set()
    for item in items:
        if not item or _is_low_information_title(str(item.get("text", ""))):
            continue
        text_key = str(item.get("text", "")).lower().strip()
        signature = "::".join(
            str(item.get(key, "")).lower()
            for key in ("family", "entity", "target_field", "polarity", "text")
        )
        if text_key in text_seen or signature in seen:
            continue
        if any(
            item.get("family") == existing.get("family")
            and SequenceMatcher(None, text_key, str(existing.get("text", "")).lower()).ratio() >= 0.92
            for existing in out
        ):
            continue
        seen.add(signature)
        text_seen.add(text_key)
        out.append(item)
    return out


def _infer_default_screen_hint(story: JiraStory) -> Optional[str]:
    if story.key_ui_steps and ">>" in story.key_ui_steps:
        parts = [part.strip() for part in story.key_ui_steps.split(">>") if part.strip()]
        if parts:
            return parts[-1]
    for source in (story.impacted_areas, story.summary):
        if not source:
            continue
        if not any(token in source.lower() for token in ("screen", "grid", "decision", "list", "drawer")):
            continue
        match = re.search(r"([A-Za-z][A-Za-z0-9 /_-]{3,50})", source)
        if match:
            return match.group(1).strip()
    return None


def _normalise_story_scope_defaults(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "lob_scope": {"mode": "all", "values": []},
            "stage_scope": {"mode": "all", "values": []},
        }
    return {
        "lob_scope": _normalise_scope(raw.get("lob_scope")),
        "stage_scope": _normalise_scope(raw.get("stage_scope")),
    }


def _normalise_scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"mode": "all", "values": []}
    mode = str(raw.get("mode", "all")).strip().lower()
    if mode not in {"all", "specific"}:
        mode = "all"
    values = []
    seen = set()
    for value in raw.get("values") or []:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        values.append(text)
    return {"mode": mode, "values": values}


def _is_specific_scope(scope: Optional[dict[str, Any]]) -> bool:
    return bool(scope and scope.get("mode") == "specific" and scope.get("values"))
