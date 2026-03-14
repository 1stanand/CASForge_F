"""
llm/feature_assembler.py
------------------------
Deterministic multi-pass anchored scenario construction with scope-aware planning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import logging
import re
from typing import Any, Optional

from casforge.storage.connection import get_conn, get_cursor
from casforge.parsing.jira_parser import JiraStory
from casforge.retrieval.retrieval import search
from casforge.shared.paths import TEMPLATES_DIR
from casforge.workflow.ordering import detect_stage, detect_sub_tags
from casforge.generation.intent_extractor import coerce_intents, normalise_story_scope_defaults
from casforge.generation.scenario_planner import build_scenario_plan_items, public_intent_records

_log = logging.getLogger(__name__)

_ORDERED_TEMPLATE = TEMPLATES_DIR / "ordered.feature"
_UNORDERED_TEMPLATE = TEMPLATES_DIR / "unordered.feature"

_STEP_LINE = re.compile(r"^(\s*)(Given|When|Then|And|But)\s+(.*\S)\s*$")
_PLACEHOLDER_RE = re.compile(r"<([^>]+)>")
_ACTION_KEYWORDS = {"When", "And", "But"}
_MAX_SETUP_STEPS = 6
_MAX_ACTION_CONT = 3
_MAX_ANCHOR_VARIANTS = 1

_INTENT_STOPWORDS = {
    "user", "users", "system", "screen", "page", "field", "fields",
    "should", "able", "allow", "allows", "using", "with", "from",
    "that", "this", "when", "where", "which", "into", "for", "and",
    "the", "all", "any", "one", "more", "less", "than", "only",
    "details", "data", "application", "loan", "credit",
}

_ACTION_VERBS = {
    "click", "select", "enter", "navigate", "open", "choose", "save",
    "update", "remove", "add", "move", "submit", "perform", "proceed",
}

_ASSERTION_HINTS = {
    "visible", "display", "shown", "saved", "updated", "created", "deleted",
    "error", "message", "mandatory", "enabled", "disabled", "success",
    "persist", "retained", "derived", "calculated", "validated", "rejected",
}

_FAMILY_SECTION = {
    "positive": "Core Flow Coverage",
    "validation": "Validation Coverage",
    "negative": "Negative Coverage",
    "dependency": "Dependency Coverage",
    "state_movement": "State Movement Coverage",
    "persistence": "Persistence Coverage",
    "data_combination": "Data Combination Coverage",
    "edge": "Edge Coverage",
}

_SECTION_ORDER = [
    "positive",
    "validation",
    "negative",
    "dependency",
    "state_movement",
    "persistence",
    "data_combination",
    "edge",
]

_SECTION_KEY_ORDER = {
    "ui_structure": 0,
    "checkbox_state": 1,
    "dependency": 2,
    "field_enablement": 3,
    "decision_logic": 4,
    "validation": 5,
    "state_movement": 6,
    "persistence": 7,
    "data_combination": 8,
    "edge": 9,
    "core_flow": 10,
}

_LOB_SCOPE_ALIASES: dict[str, tuple[str, ...]] = {
    "OMNI": ("omni loan", "omni"),
    "HL": ("home loan",),
    "PL": ("personal loan",),
    "LAP": ("loan against property", "lap"),
    "MHL": ("micro home loan", "mhl"),
    "CV": ("commercial vehicle", "consumer vehicle", "cv"),
    "EDU": ("education loan", "education", "edu"),
    "PF": ("personal finance", "pf"),
    "BL": ("business loan", "bl"),
}

_EXPECTED_OUTCOME_TERMS: dict[str, set[str]] = {
    "validation_error": {"validation", "error", "message", "mandatory", "popup"},
    "disabled": {"disabled", "disable", "readonly", "read", "only", "isenabled"},
    "enabled": {"enabled", "enable", "editable", "isenabled"},
    "checked": {"checked", "selected"},
    "display": {"display", "visible", "show", "shown", "availability"},
    "save_success": {"save", "saved", "success", "updated"},
    "derived_value": {"derived", "calculate", "calculated", "value"},
    "persistence": {"persist", "retained", "reopen"},
    "state_change": {"move", "stage", "next", "updated"},
}

_STRICT_ASSERTION_OUTCOMES = {
    "validation_error",
    "disabled",
    "enabled",
    "checked",
    "derived_value",
    "persistence",
    "state_change",
}

_SPECIFICITY_CONFLICTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("credit card", "primary card", "add on card", "addon card"), ("credit card", "card", "primary card", "add on card", "addon card")),
    (("sub loan", "subloan"), ("sub loan", "subloan")),
    (("checkbox",), ("checkbox", "check box", "checked")),
)

@dataclass
class ScenarioPlan:
    intent_id: str
    intent: str
    family: str
    section_key: str
    section: str
    title: str
    given_steps: list[str]
    when_steps: list[str]
    then_step: str
    then_and_step: Optional[str]
    placeholders: list[str]
    tags: list[str]
    effective_scope: dict[str, Any]
    unresolved_assertion: bool = False
    confidence: float = 0.0
    anchor_file: Optional[str] = None
    anchor_title: Optional[str] = None
    assertion_source: str = "local"
    rejected_candidate_counts: dict[str, int] = field(default_factory=dict)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyResult:
    feature_text: str
    intents: list[dict[str, Any]]
    quality: dict[str, Any] = field(default_factory=dict)
    unresolved_steps: list[dict[str, Any]] = field(default_factory=list)
    scenario_debug: list[dict[str, Any]] = field(default_factory=list)
    coverage_gaps: list[dict[str, Any]] = field(default_factory=list)
    omitted_plan_items: list[dict[str, Any]] = field(default_factory=list)


def assemble_feature(
    story: JiraStory,
    intents: list[Any],
    flow_type: str,
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> str:
    return assemble_feature_result(
        story=story,
        intents=intents,
        flow_type=flow_type,
        story_scope_defaults=story_scope_defaults,
    ).feature_text


def assemble_feature_result(
    story: JiraStory,
    intents: list[Any],
    flow_type: str,
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> AssemblyResult:
    if flow_type not in {"ordered", "unordered"}:
        raise ValueError("flow_type must be 'ordered' or 'unordered'")

    defaults = normalise_story_scope_defaults(story_scope_defaults)
    structured_intents = coerce_intents(intents, story_scope_defaults=defaults)
    if not structured_intents:
        raise ValueError(f"No intents provided for story {story.issue_key}")

    internal_intents = build_scenario_plan_items(
        story=story,
        story_scope_defaults=defaults,
        intents=structured_intents,
    )
    public_intents = public_intent_records(internal_intents)

    stage_scope = defaults.get("stage_scope", {})
    detected_stage = None
    if _is_specific_scope(stage_scope):
        for value in stage_scope.get("values") or []:
            detected_stage = value if str(value).startswith("@") else detect_stage(str(value))
            if detected_stage:
                break
    stage_query = " ".join(part for part in (story.summary, story.impacted_areas, story.new_process[:240]) if part).strip()
    if not detected_stage:
        detected_stage = detect_stage(stage_query)
    detected_sub_tags = detect_sub_tags(stage_query)

    quality = {
        "intents_total": len(public_intents),
        "intents_planned": 0,
        "scenario_count": 0,
        "removed_out_of_scope_candidates": 0,
        "scope_relaxations": 0,
        "unresolved_assertions": 0,
        "total_steps": 0,
        "grounded_steps": 0,
        "unresolved_steps": 0,
        "coverage_gaps": 0,
        "omitted_plan_items": 0,
    }

    plans, scenario_debug, coverage_gaps, omitted_plan_items = _plan_scenarios(
        intents=internal_intents,
        flow_type=flow_type,
        detected_stage=detected_stage,
        detected_sub_tags=detected_sub_tags,
        story_scope_defaults=defaults,
        quality=quality,
    )

    quality["intents_planned"] = len({p.intent_id for p in plans})
    quality["scenario_count"] = len(plans)
    quality["unresolved_assertions"] = sum(1 for p in plans if p.unresolved_assertion)
    quality["coverage_gaps"] = len(coverage_gaps)
    quality["omitted_plan_items"] = len(omitted_plan_items)

    template_text = _load_template(flow_type)
    rendered = _render_feature(
        story=story,
        flow_type=flow_type,
        template_text=template_text,
        scenario_plans=plans,
        story_scope_defaults=defaults,
        detected_stage=detected_stage,
        detected_sub_tags=detected_sub_tags,
    )

    grounded_text, unresolved_steps, total_steps, grounded_steps = _ground_steps_to_repo(rendered)
    quality["total_steps"] = total_steps
    quality["grounded_steps"] = grounded_steps
    quality["unresolved_steps"] = len(unresolved_steps)

    return AssemblyResult(
        feature_text=grounded_text,
        intents=public_intents,
        quality=quality,
        unresolved_steps=unresolved_steps,
        scenario_debug=scenario_debug,
        coverage_gaps=coverage_gaps,
        omitted_plan_items=omitted_plan_items,
    )


def _load_template(flow_type: str) -> str:
    path = _ORDERED_TEMPLATE if flow_type == "ordered" else _UNORDERED_TEMPLATE
    if not path.is_file():
        raise FileNotFoundError(f"Template not found: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _plan_scenarios(
    intents: list[dict[str, Any]],
    flow_type: str,
    detected_stage: Optional[str],
    detected_sub_tags: list[str],
    story_scope_defaults: dict[str, Any],
    quality: dict[str, Any],
) -> tuple[list[ScenarioPlan], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plans: list[ScenarioPlan] = []
    scenario_debug: list[dict[str, Any]] = []
    coverage_gaps: list[dict[str, Any]] = []
    omitted_plan_items: list[dict[str, Any]] = []

    for ordinal, intent in enumerate(intents, 1):
        text = str(intent.get("text", "")).strip()
        if not text:
            continue

        family = _normalise_family(intent.get("family"))
        section_key = str(intent.get("section_key") or family).strip().lower() or family
        section = str(intent.get("section_title") or _FAMILY_SECTION.get(family, "Additional Coverage")).strip()
        scope = _effective_scope(intent, story_scope_defaults)

        anchors, removed, relaxed, rejected_counts = _select_anchor_variants(
            intent=intent,
            effective_scope=scope,
            detected_stage=detected_stage,
            max_variants=_MAX_ANCHOR_VARIANTS,
        )
        quality["removed_out_of_scope_candidates"] += removed
        quality["scope_relaxations"] += relaxed

        if not anchors:
            scaffold = _build_scaffold_plan_from_related_hits(
                intent=intent,
                flow_type=flow_type,
                family=family,
                section_key=section_key,
                section=section,
                effective_scope=scope,
                detected_stage=detected_stage,
                detected_sub_tags=detected_sub_tags,
                ordinal=ordinal,
                rejected_candidate_counts=rejected_counts,
            )
            if scaffold and _plan_confident_enough(scaffold):
                plans.append(scaffold)
                scenario_debug.append(_scenario_debug_entry(scaffold))
                continue
            coverage_gap = {
                "intent_id": intent.get("id") or f"intent_{ordinal:03d}",
                "intent": text,
                "family": family,
                "reason": "no_eligible_anchor",
                "rejected_candidate_counts": rejected_counts,
            }
            coverage_gaps.append(coverage_gap)
            omitted_plan_items.append(coverage_gap)
            scenario_debug.append(coverage_gap)
            continue

        accepted = False
        for variant_idx, anchor in enumerate(anchors, 1):
            plan = _build_plan_from_anchor(
                intent=intent,
                flow_type=flow_type,
                family=family,
                section_key=section_key,
                section=section,
                anchor=anchor,
                variant_idx=variant_idx,
                detected_stage=detected_stage,
                detected_sub_tags=detected_sub_tags,
                effective_scope=scope,
                ordinal=ordinal,
                rejected_candidate_counts=rejected_counts,
            )
            if not plan:
                continue
            if not _plan_confident_enough(plan):
                omitted = {
                    "intent_id": plan.intent_id,
                    "intent": text,
                    "family": family,
                    "reason": "low_confidence",
                    "confidence": round(plan.confidence, 3),
                    "anchor_file": plan.anchor_file,
                    "anchor_title": plan.anchor_title,
                    "rejected_candidate_counts": rejected_counts,
                }
                coverage_gaps.append(omitted)
                omitted_plan_items.append(omitted)
                scenario_debug.append(omitted)
                continue
            accepted = True
            plans.append(plan)
            scenario_debug.append(_scenario_debug_entry(plan))

        if not accepted:
            fallback = _build_fallback_plan(
                intent=intent,
                family=family,
                section_key=section_key,
                section=section,
                flow_type=flow_type,
                effective_scope=scope,
                detected_stage=detected_stage,
                detected_sub_tags=detected_sub_tags,
                ordinal=ordinal,
                rejected_candidate_counts=rejected_counts,
            )
            if fallback and _plan_confident_enough(fallback):
                plans.append(fallback)
                scenario_debug.append(_scenario_debug_entry(fallback))
            else:
                coverage_gap = {
                    "intent_id": intent.get("id") or f"intent_{ordinal:03d}",
                    "intent": text,
                    "family": family,
                    "reason": "omitted_after_confidence_gate",
                    "rejected_candidate_counts": rejected_counts,
                }
                coverage_gaps.append(coverage_gap)
                omitted_plan_items.append(coverage_gap)
                scenario_debug.append(coverage_gap)

    return _dedupe_plans(plans), scenario_debug, coverage_gaps, omitted_plan_items


def _normalise_family(raw: Any) -> str:
    value = str(raw or "positive").strip().lower().replace(" ", "_")
    return value if value in _FAMILY_SECTION else "positive"


def _effective_scope(intent: dict[str, Any], story_scope_defaults: dict[str, Any]) -> dict[str, Any]:
    inherit = bool(intent.get("inherit_story_scope", True))
    default_lob = _normalise_scope(story_scope_defaults.get("lob_scope"))
    default_stage = _normalise_scope(story_scope_defaults.get("stage_scope"))
    lob = _normalise_scope(intent.get("lob_scope"))
    stage = _normalise_scope(intent.get("stage_scope"))

    if inherit:
        eff_lob = lob if _is_specific_scope(lob) else default_lob
        eff_stage = stage if _is_specific_scope(stage) else default_stage
    else:
        eff_lob = lob if lob else default_lob
        eff_stage = stage if stage else default_stage

    return {"lob_scope": eff_lob, "stage_scope": eff_stage}


def _normalise_scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"mode": "all", "values": []}
    mode = str(raw.get("mode", "all")).strip().lower()
    if mode not in {"all", "specific"}:
        mode = "all"
    values = []
    seen = set()
    for item in raw.get("values", []) or []:
        txt = str(item).strip()
        if not txt:
            continue
        key = txt.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(txt)
    return {"mode": mode, "values": values}


def _is_specific_scope(scope: dict[str, Any]) -> bool:
    return scope.get("mode") == "specific" and bool(scope.get("values"))


def _intent_anchor_context(
    intent: dict[str, Any],
    effective_scope: dict[str, Any],
    detected_stage: Optional[str],
) -> dict[str, Any]:
    text = str(intent.get("text", "")).strip()
    action_target = _normalize_step_text(str(intent.get("action_target", "")))
    screen_hint = _normalize_step_text(str(intent.get("screen_hint", "")))
    expected_outcome = _normalize_step_text(str(intent.get("expected_outcome", "")))
    entity = _normalize_step_text(str(intent.get("entity", "")))
    target_field = _normalize_step_text(str(intent.get("target_field", "")))
    expected_state = _normalize_step_text(str(intent.get("expected_state", "")))
    polarity = _normalize_step_text(str(intent.get("polarity", "")))
    must_anchor_terms = [_normalize_step_text(str(term)) for term in (intent.get("must_anchor_terms") or []) if str(term).strip()]
    must_assert_terms = [_normalize_step_text(str(term)) for term in (intent.get("must_assert_terms") or []) if str(term).strip()]
    forbidden_terms = [_normalize_step_text(str(term)) for term in (intent.get("forbidden_terms") or []) if str(term).strip()]
    pattern_terms = [_normalize_step_text(str(term)) for term in (intent.get("pattern_terms") or []) if str(term).strip()]
    section_key = str(intent.get("section_key") or _normalise_family(intent.get("family"))).strip().lower()

    search_parts = [text]
    lob_scope = effective_scope.get("lob_scope", {})
    if _is_specific_scope(lob_scope):
        for value in lob_scope.get("values") or []:
            part = _normalize_step_text(str(value))
            if part and _meaningful_overlap(part, " ".join(search_parts)) < 0.50:
                search_parts.append(part)
    for part in (action_target, screen_hint, entity, target_field):
        if part and _meaningful_overlap(part, " ".join(search_parts)) < 0.50:
            search_parts.append(part)
    for term in must_anchor_terms[:2]:
        if term and _meaningful_overlap(term, " ".join(search_parts)) < 0.50:
            search_parts.append(term)
    for term in pattern_terms[:3]:
        if term and _meaningful_overlap(term, " ".join(search_parts)) < 0.50:
            search_parts.append(term)
    if expected_outcome and expected_outcome.lower() not in {"display", "persistence", "state_change"}:
        search_parts.append(expected_outcome)
    if expected_state and expected_state.lower() not in {"display", expected_outcome.lower() if expected_outcome else ""}:
        search_parts.append(expected_state)
    search_text = " ".join(part for part in search_parts if part).strip()

    query = search_text
    if _is_specific_scope(effective_scope.get("stage_scope", {})):
        query = f"{search_text} at {' '.join(effective_scope['stage_scope'].get('values', []))}".strip()
    elif detected_stage:
        query = f"{search_text} at {detected_stage.lstrip('@').lower()} stage".strip()

    return {
        "text": text,
        "search_text": search_text or text,
        "query": query or text,
        "action_target": action_target,
        "screen_hint": screen_hint,
        "expected_outcome": expected_outcome,
        "entity": entity,
        "target_field": target_field,
        "expected_state": expected_state,
        "polarity": polarity,
        "must_anchor_terms": must_anchor_terms,
        "must_assert_terms": must_assert_terms,
        "forbidden_terms": forbidden_terms,
        "pattern_terms": pattern_terms,
        "family": _normalise_family(intent.get("family")),
        "section_key": section_key,
        "matrix_signature": str(intent.get("matrix_signature") or "base"),
    }


def _select_anchor_variants(
    intent: dict[str, Any],
    effective_scope: dict[str, Any],
    detected_stage: Optional[str],
    max_variants: int,
) -> tuple[list[dict[str, Any]], int, int, dict[str, int]]:
    context = _intent_anchor_context(intent, effective_scope, detected_stage)
    hits = search(query=context["query"], top_k=60)
    if not hits:
        return [], 0, 0, {"no_hits": 1}

    groups = _group_hits_by_scenario(hits)
    removed = 0
    relaxed = 0
    candidates: list[dict[str, Any]] = []
    rejected_counts: dict[str, int] = {}

    for group in groups:
        anchor, reason = _select_scenario_anchor(group, context, effective_scope, detected_stage)
        if anchor:
            candidates.append(anchor)
        else:
            removed += 1
            key = reason or "rejected"
            rejected_counts[key] = rejected_counts.get(key, 0) + 1

    scope_required = (
        _is_specific_scope(effective_scope.get("stage_scope", {}))
        or _is_specific_scope(effective_scope.get("lob_scope", {}))
    )
    if not candidates and scope_required:
        relaxed = 1
        relaxed_scope = {
            "lob_scope": {"mode": "all", "values": []},
            "stage_scope": {"mode": "all", "values": []},
        }
        removed = 0
        for group in groups:
            anchor, reason = _select_scenario_anchor(group, context, relaxed_scope, detected_stage)
            if anchor:
                anchor["scope_relaxed"] = True
                candidates.append(anchor)
            else:
                key = f"relaxed_{reason or 'rejected'}"
                rejected_counts[key] = rejected_counts.get(key, 0) + 1

    if not candidates:
        return [], removed, relaxed, rejected_counts

    ranked = sorted(candidates, key=lambda item: item.get("anchor_scenario_score", 0.0), reverse=True)
    best_score = float(ranked[0].get("anchor_scenario_score", 0.0))
    chosen: list[dict[str, Any]] = []
    for candidate in ranked:
        score = float(candidate.get("anchor_scenario_score", 0.0))
        if chosen and score < best_score * 0.93:
            break
        if chosen and not _anchors_distinct(chosen[0], candidate):
            continue
        chosen.append(candidate)
        if len(chosen) >= max(1, max_variants):
            break

    return chosen, removed, relaxed, rejected_counts


def _group_hits_by_scenario(hits: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        key = _scenario_key(hit)
        grouped.setdefault(key, []).append(hit)

    return sorted(
        grouped.values(),
        key=lambda group: max(float(item.get("score", 0.0)) for item in group),
        reverse=True,
    )


def _scenario_key(hit: dict[str, Any]) -> str:
    file_path = str(hit.get("file_path", "")).strip()
    scenario_title = str(hit.get("scenario_title", "")).strip()
    screen_context = str(hit.get("screen_context", "")).strip()
    return "::".join([file_path, scenario_title, screen_context])


def _select_scenario_anchor(
    group: list[dict[str, Any]],
    context: dict[str, Any],
    effective_scope: dict[str, Any],
    detected_stage: Optional[str],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    anchor = _pick_group_anchor_step(group, context["search_text"])
    if not anchor:
        return None, "no_anchor"
    rejection = _candidate_rejection_reason(anchor, context, effective_scope)
    if rejection:
        return None, rejection

    scenario_blob = _scenario_context_blob(anchor)
    score = _anchor_rank(anchor, context["search_text"])
    score += 0.24 * _meaningful_overlap(context["search_text"], scenario_blob)
    score += 0.16 * _overlap_ratio(context["search_text"], scenario_blob)
    score += _scope_alignment_bonus(anchor, effective_scope, detected_stage)
    score += _screen_alignment_bonus(anchor, context)
    score += _action_target_bonus(anchor, context)
    score += _expected_outcome_bonus(anchor, context)
    score += _local_assertion_bonus(anchor, context["search_text"])
    score += _entity_alignment_bonus(anchor, context)
    score += _polarity_alignment_bonus(anchor, context)
    score += _family_alignment_bonus(anchor, context)
    score += _section_alignment_bonus(anchor, context)
    score += _matrix_alignment_bonus(anchor, context)

    candidate = dict(anchor)
    candidate["anchor_scenario_score"] = score
    candidate["anchor_query"] = context["query"]
    candidate["anchor_context_blob"] = scenario_blob
    return candidate, None


def _pick_group_anchor_step(group: list[dict[str, Any]], intent_text: str) -> Optional[dict[str, Any]]:
    action_hits = [
        h for h in group
        if h.get("keyword") in _ACTION_KEYWORDS
        and h.get("step_text")
        and _is_user_action_step(str(h.get("step_text", "")))
    ]
    synthetic_action_hits = [h for h in _synthetic_action_hits(group) if _is_user_action_step(str(h.get("step_text", "")))]
    pool = action_hits or synthetic_action_hits or [
        h for h in group
        if h.get("step_text") and not _is_assertion_like(str(h.get("step_text", "")))
    ]
    if not pool:
        return None

    ranked = sorted(pool, key=lambda h: _anchor_rank(h, intent_text), reverse=True)
    aligned = [h for h in ranked if _anchor_matches_intent(h, intent_text)]
    return (aligned or ranked)[0] if (aligned or ranked) else None


def _synthetic_action_hits(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not group:
        return []
    representative = group[0]
    scenario_steps = representative.get("scenario_steps") or []
    hits: list[dict[str, Any]] = []
    for step in scenario_steps:
        keyword = str(step.get("keyword", "")).strip()
        step_text = str(step.get("step_text", "")).strip()
        if keyword not in _ACTION_KEYWORDS or not step_text:
            continue
        candidate = dict(representative)
        candidate["keyword"] = keyword
        candidate["step_text"] = step_text
        candidate["screen_context"] = step.get("screen_context") or representative.get("screen_context")
        candidate["synthetic_anchor"] = True
        hits.append(candidate)
    return hits


def _hit_in_scope(hit: dict[str, Any], effective_scope: dict[str, Any]) -> bool:
    stage_scope = effective_scope.get("stage_scope", {"mode": "all", "values": []})
    lob_scope = effective_scope.get("lob_scope", {"mode": "all", "values": []})

    if _is_specific_scope(stage_scope):
        wanted = _scope_stage_aliases(stage_scope.get("values") or [])
        candidate = _hit_stage_aliases(hit)
        if not candidate or not (wanted & candidate):
            return False

    if _is_specific_scope(lob_scope):
        wanted = _scope_lob_aliases(lob_scope.get("values") or [])
        candidate = _hit_lob_aliases(hit)
        if not candidate or not (wanted & candidate):
            return False

    return True


def _scope_stage_aliases(values: list[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        out.add(_norm_token(text))
        tag = text if text.startswith("@") else detect_stage(text)
        if tag:
            out.add(_norm_token(tag))
            out.add(_norm_token(tag.lstrip("@")))
    return out


def _hit_stage_aliases(hit: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for tag in (hit.get("scope_stage_tags") or []):
        out.add(_norm_token(tag))
        out.add(_norm_token(str(tag).lstrip("@")))
    for stage in (hit.get("scope_application_stages") or []):
        out.add(_norm_token(stage))
        det = detect_stage(str(stage))
        if det:
            out.add(_norm_token(det))
            out.add(_norm_token(det.lstrip("@")))
    for text in (hit.get("scenario_title", ""), hit.get("file_path", ""), hit.get("screen_context", "")):
        det = detect_stage(str(text))
        if det:
            out.add(_norm_token(det))
            out.add(_norm_token(det.lstrip("@")))
    return {x for x in out if x}


def _scope_lob_aliases(values: list[str]) -> set[str]:
    out: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        upper = text.upper()
        out.add(_norm_token(text))
        out.add(_norm_token(upper))
        for phrase in _LOB_SCOPE_ALIASES.get(upper, (text,)):
            out.add(_norm_token(phrase))
    return {x for x in out if x}


def _hit_lob_aliases(hit: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for value in (hit.get("scope_product_types") or []):
        out.add(_norm_token(value))
        out.add(_norm_token(str(value).upper()))
    blob = _scenario_context_blob(hit)
    file_path = str(hit.get("file_path", "")).lower()
    for canonical, phrases in _LOB_SCOPE_ALIASES.items():
        if any((phrase in blob) or (phrase in file_path) for phrase in phrases):
            out.add(_norm_token(canonical))
            for phrase in phrases:
                out.add(_norm_token(phrase))
    return {x for x in out if x}


def _scenario_context_blob(hit: dict[str, Any]) -> str:
    parts = [
        str(hit.get("scenario_title", "")),
        str(hit.get("screen_context", "")),
    ]
    for step in (hit.get("scenario_steps") or [])[:6]:
        parts.append(_normalize_step_text(str(step.get("step_text", ""))))
    return " ".join(part for part in parts if part).strip().lower()


def _scenario_domain_ok(hit: dict[str, Any], context: dict[str, Any]) -> bool:
    scenario_blob = _scenario_context_blob(hit)
    search_text = context.get("search_text", "")
    screen_hint = context.get("screen_hint", "")
    action_target = context.get("action_target", "")
    section_key = str(context.get("section_key", "")).strip().lower()

    if screen_hint:
        screen_overlap = max(
            _meaningful_overlap(screen_hint, str(hit.get("screen_context", ""))),
            _meaningful_overlap(screen_hint, str(hit.get("scenario_title", ""))),
            _meaningful_overlap(screen_hint, scenario_blob),
        )
        min_screen_overlap = 0.20 if section_key in {"state_movement", "field_enablement", "checkbox_state"} else 0.14
        if screen_overlap < min_screen_overlap:
            return False

    if action_target:
        target_overlap = max(
            _meaningful_overlap(action_target, str(hit.get("step_text", ""))),
            _meaningful_overlap(action_target, scenario_blob),
        )
        if target_overlap < 0.08:
            return False

    if section_key in {"state_movement", "field_enablement", "decision_logic", "checkbox_state"}:
        context_domain_terms = _domain_specific_terms(" ".join([
            search_text,
            screen_hint,
            " ".join(context.get("pattern_terms") or []),
            str(context.get("entity", "")),
            str(context.get("target_field", "")),
        ]))
        candidate_domain_terms = _domain_specific_terms(" ".join([
            str(hit.get("file_path", "")),
            str(hit.get("scenario_title", "")),
            str(hit.get("screen_context", "")),
        ]))
        if context_domain_terms and candidate_domain_terms and not (context_domain_terms & candidate_domain_terms):
            return False

    scenario_overlap = max(
        _meaningful_overlap(search_text, scenario_blob),
        _overlap_ratio(search_text, str(hit.get("step_text", ""))),
    )
    return scenario_overlap >= 0.12


def _candidate_rejection_reason(hit: dict[str, Any], context: dict[str, Any], effective_scope: dict[str, Any]) -> Optional[str]:
    if (_is_specific_scope(effective_scope.get("stage_scope", {})) or _is_specific_scope(effective_scope.get("lob_scope", {}))) and not _hit_in_scope(hit, effective_scope):
        return "scope_mismatch"
    if not _scenario_domain_ok(hit, context):
        return "domain_mismatch"
    if not _entity_matches_context(hit, context):
        return "entity_mismatch"
    if not _polarity_matches_context(hit, context):
        return "polarity_mismatch"
    if not _expected_outcome_matches_context(hit, context):
        return "outcome_mismatch"
    if not _family_matches_context(hit, context):
        return "family_mismatch"
    return None


def _context_blob_for_candidate(hit: dict[str, Any]) -> str:
    scenario_steps = hit.get("scenario_steps") or []
    anchor_idx = _find_anchor_index(hit, scenario_steps)
    local_then, local_and = _collect_local_assertions(scenario_steps, anchor_idx, str(hit.get("step_text", "")), hit) if scenario_steps and anchor_idx >= 0 else (None, None)
    parts = [
        _scenario_context_blob(hit),
        _normalize_step_text(str(local_then or "")),
        _normalize_step_text(str(local_and or "")),
        _normalize_step_text(str(hit.get("step_text", ""))),
    ]
    return " ".join(part for part in parts if part).strip().lower()


def _entity_matches_context(hit: dict[str, Any], context: dict[str, Any]) -> bool:
    entity = str(context.get("entity", "")).strip()
    target_field = str(context.get("target_field", "")).strip()
    must_terms = [term for term in (context.get("must_anchor_terms") or []) if len(term) >= 3]
    blob = _context_blob_for_candidate(hit)

    if entity and max(_meaningful_overlap(entity, blob), _overlap_ratio(entity, blob)) < 0.08:
        return False
    if target_field and max(_meaningful_overlap(target_field, blob), _overlap_ratio(target_field, blob)) < 0.08:
        return False
    specific_target_terms = _specific_target_terms(" ".join(part for part in (target_field, entity) if part))
    if specific_target_terms:
        matched_specific = specific_target_terms & _tokenize(blob)
        min_required = len(specific_target_terms) if len(specific_target_terms) <= 2 else len(specific_target_terms) - 1
        if len(matched_specific) < min_required:
            return False
    if must_terms and not any(_meaningful_overlap(term, blob) >= 0.08 or _overlap_ratio(term, blob) >= 0.08 for term in must_terms[:3]):
        return False
    if _has_specificity_conflict(blob, context):
        return False
    return True


def _polarity_matches_context(hit: dict[str, Any], context: dict[str, Any]) -> bool:
    forbidden_terms = [term for term in (context.get("forbidden_terms") or []) if len(term) >= 3]
    must_terms = [term for term in (context.get("must_assert_terms") or []) if len(term) >= 3]
    blob = _context_blob_for_candidate(hit)
    if forbidden_terms and any(term.lower() in blob for term in forbidden_terms) and not any(term.lower() in blob for term in must_terms):
        return False

    polarity = str(context.get("polarity", "")).lower()
    if not polarity:
        return True
    if polarity == "disabled" and "enabled" in blob and "disabled" not in blob:
        return False
    if polarity == "enabled" and "disabled" in blob and "enabled" not in blob:
        return False
    if polarity == "checked" and "unchecked" in blob and "checked" not in blob:
        return False
    if polarity == "unchecked" and "checked" in blob and "unchecked" not in blob:
        return False
    if polarity == "not_recommended" and "recommended" in blob and "not recommended" not in blob:
        return False
    if polarity == "recommended" and "not recommended" in blob:
        return False
    return True


def _expected_outcome_matches_context(hit: dict[str, Any], context: dict[str, Any]) -> bool:
    expected_terms = _expected_outcome_terms(context)
    must_assert_terms = [term for term in (context.get("must_assert_terms") or []) if len(term) >= 3]
    blob = _context_blob_for_candidate(hit)
    if expected_terms and not (_tokenize(blob) & expected_terms):
        if must_assert_terms and not any(term.lower() in blob for term in must_assert_terms[:3]):
            return False
    return True


def _family_matches_context(hit: dict[str, Any], context: dict[str, Any]) -> bool:
    family = str(context.get("family", "positive"))
    section_key = str(context.get("section_key", "")).strip().lower()
    blob = _context_blob_for_candidate(hit)
    tokens = _tokenize(blob)
    if section_key == "ui_structure":
        return bool(tokens & {"display", "visible", "show", "column", "availability", "grid", "screen"})
    if section_key == "checkbox_state":
        outcome = str(context.get("expected_outcome", "")).strip().lower()
        if outcome == "checked":
            return bool(tokens & {"checked", "default", "selected", "auto", "populated"})
        if outcome == "enabled":
            return bool(tokens & {"checkbox"}) and bool(tokens & {"enabled", "editable", "selected"})
        if outcome == "disabled":
            return bool(tokens & {"checkbox"}) and bool(tokens & {"disabled", "unchecked"})
        return bool(tokens & {"checkbox"}) and bool(tokens & {"display", "visible", "show", "column", "availability", "checked", "enabled"})
    if section_key == "field_enablement":
        return bool(tokens & {"enabled", "disabled", "editable", "readonly", "field", "limit", "amount"})
    if section_key == "decision_logic":
        return bool(tokens & {"decision", "dropdown", "verdict", "recommended", "approved", "rejected"})
    if section_key == "state_movement":
        return bool(tokens & {"move", "stage", "next", "credit", "recommendation", "approval", "reconsideration"})
    if section_key == "persistence":
        return bool(tokens & {"save", "saved", "retain", "retained", "persist", "reopen"})
    if section_key == "data_combination":
        return bool(tokens & {"any", "all", "none", "mixed", "combination"})
    if family == "validation":
        return bool(tokens & {"validation", "mandatory", "required", "error", "invalid", "zero", "reject"})
    if family == "dependency":
        return bool(tokens & {"based", "same", "derived", "enable", "disable", "selected", "decision"})
    if family == "state_movement":
        return bool(tokens & {"move", "stage", "next", "credit", "recommendation", "approval"})
    if family == "persistence":
        return bool(tokens & {"save", "saved", "retain", "retained", "persist", "reopen"})
    if family == "negative":
        return bool(tokens & {"error", "reject", "invalid", "prevent", "disabled"})
    return True


def _entity_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    bonus = 0.0
    blob = _context_blob_for_candidate(hit)
    for part in (context.get("entity", ""), context.get("target_field", "")):
        if part:
            bonus += 0.10 * max(_meaningful_overlap(str(part), blob), _overlap_ratio(str(part), blob))
    return bonus


def _polarity_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    polarity = str(context.get("polarity", "")).lower()
    if not polarity:
        return 0.0
    blob = _context_blob_for_candidate(hit)
    if polarity in blob:
        return 0.12
    expected_terms = _expected_outcome_terms(context)
    if expected_terms and (_tokenize(blob) & expected_terms):
        return 0.06
    return 0.0


def _family_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    return 0.08 if _family_matches_context(hit, context) else 0.0


def _section_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    section_key = str(context.get("section_key", "")).strip().lower()
    if not section_key:
        return 0.0
    blob = _context_blob_for_candidate(hit)
    terms_by_section = {
        "ui_structure": {"display", "visible", "show", "column", "availability", "grid", "screen"},
        "checkbox_state": {"checkbox", "checked", "unchecked", "default", "selected", "enabled", "disabled"},
        "dependency": {"derived", "based", "depends", "same", "selected", "if", "any", "all"},
        "field_enablement": {"enabled", "disabled", "editable", "readonly", "field", "limit", "amount"},
        "decision_logic": {"decision", "dropdown", "verdict", "recommended", "approved", "rejected"},
        "validation": {"validation", "error", "invalid", "mandatory", "required", "zero"},
        "state_movement": {"move", "stage", "next", "approval", "rejected", "credit"},
        "persistence": {"save", "saved", "retain", "retained", "persist", "reopen"},
        "data_combination": {"any", "all", "none", "mixed", "combination"},
        "edge": {"zero", "blank", "duplicate", "none"},
    }
    terms = terms_by_section.get(section_key, set())
    if not terms:
        return 0.0
    return 0.14 if (_tokenize(blob) & terms) else 0.0


def _matrix_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    matrix_signature = str(context.get("matrix_signature", "")).strip().lower()
    if not matrix_signature or matrix_signature == "base":
        return 0.0
    blob = _context_blob_for_candidate(hit)
    score = 0.0
    if "any" in matrix_signature and (_tokenize(blob) & {"any", "least", "one"}):
        score += 0.06
    if "all" in matrix_signature and "all" in _tokenize(blob):
        score += 0.06
    if "none" in matrix_signature and (_tokenize(blob) & {"none", "unchecked", "not"}):
        score += 0.06
    if "mixed" in matrix_signature and (_tokenize(blob) & {"mixed", "combination", "split"}):
        score += 0.06
    if "dependent_card" in matrix_signature and (_tokenize(blob) & {"primary", "addon", "card"}):
        score += 0.10
    if "credit_card" in matrix_signature and (_tokenize(blob) & {"credit", "card", "primary", "addon"}):
        score += 0.08
    if "subloan" in matrix_signature and (_tokenize(blob) & {"sub", "loan", "product", "products"}):
        score += 0.08
    return score


def _scope_alignment_bonus(hit: dict[str, Any], effective_scope: dict[str, Any], detected_stage: Optional[str]) -> float:
    bonus = 0.0
    if _is_specific_scope(effective_scope.get("stage_scope", {})) and _hit_in_scope(hit, {"stage_scope": effective_scope.get("stage_scope", {}), "lob_scope": {"mode": "all", "values": []}}):
        bonus += 0.16
    elif detected_stage and _norm_token(detected_stage) in _hit_stage_aliases(hit):
        bonus += 0.08

    if _is_specific_scope(effective_scope.get("lob_scope", {})) and _hit_in_scope(hit, {"stage_scope": {"mode": "all", "values": []}, "lob_scope": effective_scope.get("lob_scope", {})}):
        bonus += 0.10
    return bonus


def _screen_alignment_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    screen_hint = context.get("screen_hint", "")
    if not screen_hint:
        return 0.0
    return 0.14 * max(
        _meaningful_overlap(screen_hint, str(hit.get("screen_context", ""))),
        _meaningful_overlap(screen_hint, str(hit.get("scenario_title", ""))),
    )


def _action_target_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    action_target = context.get("action_target", "")
    if not action_target:
        return 0.0
    return 0.12 * max(
        _meaningful_overlap(action_target, str(hit.get("step_text", ""))),
        _meaningful_overlap(action_target, _scenario_context_blob(hit)),
    )


def _local_assertion_bonus(hit: dict[str, Any], intent_text: str) -> float:
    scenario_steps = hit.get("scenario_steps") or []
    if not scenario_steps:
        return 0.0
    anchor_idx = _find_anchor_index(hit, scenario_steps)
    if anchor_idx < 0:
        return 0.0
    local_then, _ = _collect_local_assertions(scenario_steps, anchor_idx, intent_text, hit)
    if local_then and _is_assertion_relevant(local_then, intent_text, str(hit.get("step_text", "")), None):
        return 0.08
    return 0.0


def _anchors_distinct(first: dict[str, Any], second: dict[str, Any]) -> bool:
    s1 = _canonical_step_text(str(first.get("step_text", "")))
    s2 = _canonical_step_text(str(second.get("step_text", "")))
    if not s1 or not s2:
        return False
    if s1 == s2:
        first_scope = (
            tuple(sorted(_norm_token(v) for v in (first.get("scope_product_types") or []))),
            tuple(sorted(_norm_token(v) for v in (first.get("scope_stage_tags") or []))),
        )
        second_scope = (
            tuple(sorted(_norm_token(v) for v in (second.get("scope_product_types") or []))),
            tuple(sorted(_norm_token(v) for v in (second.get("scope_stage_tags") or []))),
        )
        return first_scope != second_scope
    return _overlap_ratio(s1, s2) < 0.82


def _anchor_rank(hit: dict[str, Any], intent: str) -> float:
    score = float(hit.get("score", 0.0))
    kw = hit.get("keyword", "")
    if kw == "When":
        score += 0.18
    elif kw in {"And", "But"}:
        score += 0.08
    elif kw == "Then":
        score -= 0.22
    score += 0.34 * _overlap_ratio(intent, _normalize_step_text(str(hit.get("step_text", ""))))
    score += 0.20 * _meaningful_overlap(intent, str(hit.get("scenario_title", "")))
    score += min(len(hit.get("scenario_steps") or []), 10) * 0.003
    return score


def _anchor_matches_intent(hit: dict[str, Any], intent: str) -> bool:
    terms = _meaningful_terms(intent)
    if not terms:
        return True
    blob = _scenario_context_blob(hit)
    matched = sum(1 for t in terms if t in blob)
    required = 1 if len(terms) <= 3 else 2
    return matched >= required


def _is_user_action_step(step_text: str) -> bool:
    text = _normalize_step_text(step_text)
    if not text or _is_assertion_like(text):
        return False
    lowered = text.lower()
    if lowered.startswith("user "):
        return True
    tokens = _tokenize(text)
    return bool(tokens & {"click", "clicks", "select", "selects", "enter", "enters", "open", "opens", "choose", "chooses", "save", "saves", "update", "updates", "remove", "removes", "add", "adds", "move", "moves", "submit", "submits", "perform", "performs", "proceed", "proceeds", "scroll", "scrolls", "set", "sets", "make", "makes"})


def _build_plan_from_anchor(
    intent: dict[str, Any],
    flow_type: str,
    family: str,
    section_key: str,
    section: str,
    anchor: dict[str, Any],
    variant_idx: int,
    detected_stage: Optional[str],
    detected_sub_tags: list[str],
    effective_scope: dict[str, Any],
    ordinal: int,
    rejected_candidate_counts: Optional[dict[str, int]] = None,
) -> Optional[ScenarioPlan]:
    context = _intent_anchor_context(intent, effective_scope, detected_stage)
    text = context["text"]
    query_text = context["search_text"]
    scenario_steps = anchor.get("scenario_steps") or []
    if not scenario_steps:
        return None

    anchor_idx = _find_anchor_index(anchor, scenario_steps)
    if anchor_idx < 0:
        return None

    setup = _dedupe_steps(_collect_setup_steps(scenario_steps, anchor_idx))
    actions = _dedupe_steps(_collect_action_steps(scenario_steps, anchor_idx))
    if not actions:
        action = _normalize_step_text(str(anchor.get("step_text", "")))
        actions = [action] if action else []
    if not actions:
        return None

    local_then, local_and = _collect_local_assertions(scenario_steps, anchor_idx, query_text, anchor)
    anchor_action = actions[0]
    assertion_source = "local"

    if local_then and not _is_assertion_relevant(local_then, query_text, anchor_action, context):
        local_then, local_and = None, None

    unresolved_assertion = False
    if not local_then:
        local_then, local_and = _retrieve_assertions(intent, anchor, effective_scope, detected_stage)
        assertion_source = "retrieved" if local_then else assertion_source
        if local_then and not _is_assertion_relevant(local_then, query_text, anchor_action, context):
            local_then, local_and = None, None
            assertion_source = "missing"

    if not local_then:
        local_then = _fallback_then_step(intent, anchor)
        local_and = None
        unresolved_assertion = True
        assertion_source = "fallback"

    local_and = _filter_optional_assertion(local_and, query_text, anchor_action, local_then, context)
    title = _build_scenario_title(text, variant_idx, anchor)
    tags = _build_plan_tags(anchor, detected_stage, detected_sub_tags, effective_scope)

    steps_for_placeholders = setup + actions + [local_then]
    if local_and:
        steps_for_placeholders.append(local_and)

    if flow_type == "ordered":
        given = _dedupe_steps([_fallback_given_step("ordered"), *setup])
    else:
        given = _dedupe_steps(setup if setup else [_fallback_given_step("unordered")])

    confidence = _confidence_from_components(anchor, given, actions, local_then, local_and, assertion_source, unresolved_assertion)
    return ScenarioPlan(
        intent_id=str(intent.get("id", f"intent_{ordinal:03d}")),
        intent=text,
        family=family,
        section_key=section_key,
        section=section,
        title=title,
        given_steps=given,
        when_steps=actions,
        then_step=local_then,
        then_and_step=local_and,
        placeholders=_extract_placeholders(steps_for_placeholders),
        tags=tags,
        effective_scope=effective_scope,
        unresolved_assertion=unresolved_assertion,
        confidence=confidence,
        anchor_file=str(anchor.get("file_path", "") or "") or None,
        anchor_title=str(anchor.get("scenario_title", "") or "") or None,
        assertion_source=assertion_source,
        rejected_candidate_counts=dict(rejected_candidate_counts or {}),
        debug={
            "query": context.get("query"),
            "screen_hint": context.get("screen_hint"),
            "entity": context.get("entity"),
            "polarity": context.get("polarity"),
            "expected_outcome": context.get("expected_outcome"),
            "anchor_score": round(float(anchor.get("anchor_scenario_score", 0.0)), 3),
            "scope_relaxed": bool(anchor.get("scope_relaxed")),
        },
    )


def _build_scaffold_plan_from_related_hits(
    intent: dict[str, Any],
    family: str,
    section_key: str,
    section: str,
    flow_type: str,
    effective_scope: dict[str, Any],
    detected_stage: Optional[str],
    detected_sub_tags: list[str],
    ordinal: int,
    rejected_candidate_counts: Optional[dict[str, int]] = None,
) -> Optional[ScenarioPlan]:
    context = _intent_anchor_context(intent, effective_scope, detected_stage)
    hits = search(query=context.get("query", context.get("search_text", "")), top_k=20)
    for group in _group_hits_by_scenario(hits):
        anchor = _pick_group_anchor_step(group, context.get("search_text", ""))
        if not anchor:
            continue
        if (_is_specific_scope(effective_scope.get("stage_scope", {})) or _is_specific_scope(effective_scope.get("lob_scope", {}))) and not _hit_in_scope(anchor, effective_scope):
            continue
        if not _scenario_domain_ok(anchor, context):
            continue
        if not _is_user_action_step(str(anchor.get("step_text", ""))):
            continue
        plan = _build_plan_from_anchor(
            intent=intent,
            flow_type=flow_type,
            family=family,
            section_key=section_key,
            section=section,
            anchor=anchor,
            variant_idx=1,
            detected_stage=detected_stage,
            detected_sub_tags=detected_sub_tags,
            effective_scope=effective_scope,
            ordinal=ordinal,
            rejected_candidate_counts=rejected_candidate_counts,
        )
        if not plan:
            continue
        plan.unresolved_assertion = True
        plan.assertion_source = "fallback"
        plan.confidence = max(min(plan.confidence, 0.72), 0.67)
        plan.debug["scaffold"] = True
        return plan
    return None

def _build_fallback_plan(
    intent: dict[str, Any],
    family: str,
    section_key: str,
    section: str,
    flow_type: str,
    effective_scope: dict[str, Any],
    detected_stage: Optional[str],
    detected_sub_tags: list[str],
    ordinal: int,
    rejected_candidate_counts: Optional[dict[str, int]] = None,
) -> Optional[ScenarioPlan]:
    text = str(intent.get("text", "")).strip()
    if not text:
        return None
    query = f"{text} at {detected_stage.lstrip('@')}" if detected_stage else text
    hits = search(query, top_k=3)
    if not hits:
        return None
    context = _intent_anchor_context(intent, effective_scope, detected_stage)
    eligible = [hit for hit in hits if not _candidate_rejection_reason(hit, context, effective_scope)]
    if not eligible:
        return None
    top = eligible[0]
    when_step = _normalize_step_text(str(top.get("step_text", "")))
    if not when_step:
        return None

    confidence = 0.42 + min(float(top.get("score", 0.0)), 1.0) * 0.28
    return ScenarioPlan(
        intent_id=str(intent.get("id", f"intent_{ordinal:03d}")),
        intent=text,
        family=family,
        section_key=section_key,
        section=section,
        title=text,
        given_steps=[_fallback_given_step(flow_type)],
        when_steps=[when_step],
        then_step=_fallback_then_step(text, top),
        then_and_step=None,
        placeholders=_extract_placeholders([when_step]),
        tags=_build_plan_tags(top, detected_stage, detected_sub_tags, effective_scope),
        effective_scope=effective_scope,
        unresolved_assertion=True,
        confidence=min(confidence, 0.68),
        anchor_file=str(top.get("file_path", "") or "") or None,
        anchor_title=str(top.get("scenario_title", "") or "") or None,
        assertion_source="fallback",
        rejected_candidate_counts=dict(rejected_candidate_counts or {}),
        debug={"query": query, "fallback": True},
    )


def _build_plan_tags(anchor: dict[str, Any], detected_stage: Optional[str], detected_sub_tags: list[str], effective_scope: dict[str, Any]) -> list[str]:
    tags = []
    stage_scope = effective_scope.get("stage_scope", {})
    explicit_stage = _is_specific_scope(stage_scope)
    wanted_stage_aliases = _scope_stage_aliases(stage_scope.get("values") or []) if explicit_stage else set()
    if explicit_stage:
        for value in stage_scope.get("values") or []:
            tag = value if str(value).startswith("@") else detect_stage(str(value))
            if tag:
                tags.append(tag)
        anchor_stage_tags = [
            tag for tag in (anchor.get("scope_stage_tags") or [])
            if _norm_token(tag) in wanted_stage_aliases or _norm_token(str(tag).lstrip("@")) in wanted_stage_aliases
        ]
    else:
        anchor_stage_tags = list(anchor.get("scope_stage_tags") or [])
    tags.extend(anchor_stage_tags)
    if detected_stage and not explicit_stage:
        tags.append(detected_stage)
    tags.extend(detected_sub_tags)
    tags.extend(anchor.get("scope_sub_tags") or [])

    out = []
    seen = set()
    for tag in tags:
        text = str(tag).strip()
        if not text:
            continue
        if not text.startswith("@"):
            text = f"@{text}"
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out

def _plan_confident_enough(plan: ScenarioPlan) -> bool:
    threshold = 0.58 if not plan.unresolved_assertion else 0.64
    if plan.assertion_source == "fallback":
        threshold += 0.02
    if plan.assertion_source == "fallback" and float(plan.debug.get("anchor_score", 0.0) or 0.0) <= 0.05:
        return False
    if plan.family == "state_movement" and plan.assertion_source == "fallback" and bool(plan.debug.get("scope_relaxed")):
        return False
    return plan.confidence >= threshold


def _confidence_from_components(
    anchor: dict[str, Any],
    given_steps: list[str],
    when_steps: list[str],
    then_step: str,
    then_and_step: Optional[str],
    assertion_source: str,
    unresolved_assertion: bool,
) -> float:
    confidence = 0.32
    confidence += min(float(anchor.get("anchor_scenario_score", 0.0)), 1.5) / 2.8
    if given_steps:
        confidence += min(len(given_steps), 4) * 0.015
    if when_steps:
        confidence += min(len(when_steps), 3) * 0.02
    if then_step:
        confidence += 0.08
    if then_and_step:
        confidence += 0.03
    if assertion_source == "local":
        confidence += 0.10
    elif assertion_source == "retrieved":
        confidence += 0.05
    elif assertion_source == "fallback":
        confidence -= 0.07
    if unresolved_assertion:
        confidence -= 0.08
    if anchor.get("scope_relaxed"):
        confidence -= 0.05
    return max(0.0, min(confidence, 0.99))


def _scenario_debug_entry(plan: ScenarioPlan) -> dict[str, Any]:
    return {
        "intent_id": plan.intent_id,
        "title": plan.title,
        "family": plan.family,
        "section_key": plan.section_key,
        "section": plan.section,
        "confidence": round(plan.confidence, 3),
        "anchor_file": plan.anchor_file,
        "anchor_title": plan.anchor_title,
        "assertion_source": plan.assertion_source,
        "rejected_candidate_counts": dict(plan.rejected_candidate_counts),
        "unresolved_assertion": plan.unresolved_assertion,
        "debug": dict(plan.debug),
    }


def _dedupe_plans(plans: list[ScenarioPlan]) -> list[ScenarioPlan]:
    out = []
    seen = set()
    for p in plans:
        when_sig = " | ".join(_canonical_step_text(s) for s in p.when_steps if s)
        then_sig = _canonical_step_text(p.then_step)
        scope_sig = _scope_signature(p.effective_scope)
        sig = f"{p.family}::{when_sig}::{then_sig}::{scope_sig}"
        if not when_sig or not then_sig or sig in seen:
            continue
        seen.add(sig)
        out.append(p)
    return sorted(out, key=lambda p: (_section_rank(p.section_key, p.family), -p.confidence, p.intent.lower(), p.title.lower()))


def _section_rank(section_key: str, family: str) -> int:
    key = str(section_key or "").strip().lower()
    if key in _SECTION_KEY_ORDER:
        return _SECTION_KEY_ORDER[key]
    return _SECTION_ORDER.index(family) if family in _SECTION_ORDER else len(_SECTION_ORDER) + len(_SECTION_KEY_ORDER)


def _scope_signature(scope: dict[str, Any]) -> str:
    lob = scope.get("lob_scope", {})
    stage = scope.get("stage_scope", {})
    return "|".join([
        str(lob.get("mode", "all")),
        ",".join(sorted(_norm_token(v) for v in (lob.get("values") or []))),
        str(stage.get("mode", "all")),
        ",".join(sorted(_norm_token(v) for v in (stage.get("values") or []))),
    ])


def _find_anchor_index(anchor: dict[str, Any], scenario_steps: list[dict]) -> int:
    target_kw = str(anchor.get("keyword", "")).strip().lower()
    target_txt = _canonical_step_text(str(anchor.get("step_text", "")))
    for i, step in enumerate(scenario_steps):
        kw = str(step.get("keyword", "")).strip().lower()
        txt = _canonical_step_text(str(step.get("step_text", "")))
        if kw == target_kw and txt == target_txt:
            return i
    for i, step in enumerate(scenario_steps):
        txt = _canonical_step_text(str(step.get("step_text", "")))
        if txt == target_txt:
            return i
    return -1


def _collect_setup_steps(scenario_steps: list[dict], anchor_idx: int) -> list[str]:
    raw = [_normalize_step_text(str(s.get("step_text", ""))) for s in scenario_steps[:anchor_idx]]
    raw = [x for x in raw if x]
    if len(raw) > _MAX_SETUP_STEPS:
        raw = raw[-_MAX_SETUP_STEPS:]
    return raw


def _collect_action_steps(scenario_steps: list[dict], anchor_idx: int) -> list[str]:
    actions = []
    anchor_txt = _normalize_step_text(str(scenario_steps[anchor_idx].get("step_text", "")))
    if anchor_txt:
        actions.append(anchor_txt)

    cont = 0
    for s in scenario_steps[anchor_idx + 1:]:
        kw = str(s.get("keyword", "")).strip()
        txt = _normalize_step_text(str(s.get("step_text", "")))
        if not txt:
            continue
        if kw == "Then":
            break
        if kw in _ACTION_KEYWORDS:
            if cont >= _MAX_ACTION_CONT:
                break
            actions.append(txt)
            cont += 1
        else:
            break
    return actions


def _collect_local_assertions(scenario_steps: list[dict], anchor_idx: int, intent: str, anchor: dict) -> tuple[Optional[str], Optional[str]]:
    then_step = None
    and_step = None
    found_then = False
    for step in scenario_steps[anchor_idx + 1:]:
        kw = str(step.get("keyword", "")).strip()
        txt = _normalize_step_text(str(step.get("step_text", "")))
        if not txt:
            continue
        if not found_then:
            if kw == "Then":
                then_step = txt
                found_then = True
            continue
        if kw in {"And", "But"} and and_step is None:
            and_step = txt
        break

    if then_step and and_step:
        and_step = _filter_optional_assertion(and_step, intent, str(anchor.get("step_text", "")), then_step, None)
    return then_step, and_step


def _retrieve_assertions(intent: dict[str, Any], anchor: dict, effective_scope: dict[str, Any], detected_stage: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    context = _intent_anchor_context(intent, effective_scope, detected_stage)
    anchor_text = _normalize_step_text(str(anchor.get("step_text", "")))
    stage_scope = effective_scope.get("stage_scope", {})
    scope_hint = ""
    if _is_specific_scope(stage_scope):
        scope_hint = " at " + " ".join(str(v) for v in stage_scope.get("values") or [])
    elif detected_stage:
        scope_hint = f" at {detected_stage.lstrip('@').lower()} stage"

    query_parts = [context.get("search_text", ""), context.get("expected_outcome", ""), anchor_text]
    query = " ".join(part for part in query_parts if part).strip() + scope_hint
    screen_filter = str(anchor.get("screen_context", "") or "").strip() or None

    then_hits = search(query=query.strip(), top_k=8, screen_filter=screen_filter, keyword_filter="Then")
    then_hits = [h for h in then_hits if _assertion_candidate_ok(h, context, anchor, effective_scope)]
    then_best = _pick_assertion_by_context(then_hits, context, anchor)
    if not then_best:
        return None, None

    then_text = _normalize_step_text(str(then_best.get("step_text", "")))
    if not then_text:
        return None, None

    and_hits = search(query=query.strip(), top_k=8, screen_filter=screen_filter, keyword_filter="And")
    and_hits = [h for h in and_hits if _assertion_candidate_ok(h, context, anchor, effective_scope)]
    and_best = _pick_assertion_by_context(and_hits, context, anchor)

    and_text = None
    if and_best:
        and_text = _filter_optional_assertion(and_best.get("step_text"), context.get("search_text", ""), anchor_text, then_text, context)
    return then_text, and_text


def _assertion_candidate_ok(hit: dict[str, Any], context: dict[str, Any], anchor: dict, effective_scope: dict[str, Any]) -> bool:
    txt = _normalize_step_text(str(hit.get("step_text", "")))
    if not txt or not _is_assertion_like(txt):
        return False
    if not _same_domain_family(hit, anchor):
        return False
    if not _is_assertion_relevant(txt, context.get("search_text", ""), str(anchor.get("step_text", "")), context):
        return False
    if (_is_specific_scope(effective_scope.get("stage_scope", {})) or _is_specific_scope(effective_scope.get("lob_scope", {}))) and not _hit_in_scope(hit, effective_scope):
        return False
    return True


def _same_domain_family(candidate: dict[str, Any], anchor: dict[str, Any]) -> bool:
    anchor_terms = _path_domain_terms(str(anchor.get("file_path", "")))
    candidate_terms = _path_domain_terms(str(candidate.get("file_path", "")))
    if anchor_terms and candidate_terms and not (anchor_terms & candidate_terms):
        return False

    anchor_sub = {_norm_token(v) for v in (anchor.get("scope_sub_tags") or [])}
    candidate_sub = {_norm_token(v) for v in (candidate.get("scope_sub_tags") or [])}
    if anchor_sub and candidate_sub and not (anchor_sub & candidate_sub):
        return False

    anchor_screen = str(anchor.get("screen_context", ""))
    candidate_screen = str(candidate.get("screen_context", ""))
    if anchor_screen and candidate_screen and _meaningful_overlap(anchor_screen, candidate_screen) < 0.10:
        return False
    return True


def _path_domain_terms(path_text: str) -> set[str]:
    terms = _meaningful_terms(path_text.replace("\\", " ").replace("/", " "))
    return {t for t in terms if t not in {"feature", "features", "screen", "details", "validation", "viewer"}}


def _pick_assertion_by_context(cands: list[dict], context: dict[str, Any], anchor: dict) -> Optional[dict]:
    if not cands:
        return None
    anchor_file = anchor.get("file_path")
    anchor_screen = anchor.get("screen_context")
    anchor_step = _normalize_step_text(str(anchor.get("step_text", "")))
    anchor_sub = {_norm_token(v) for v in (anchor.get("scope_sub_tags") or [])}
    expected_terms = _expected_outcome_terms(context)

    def _rank(c: dict) -> float:
        score = float(c.get("score", 0.0))
        if anchor_file and c.get("file_path") == anchor_file:
            score += 0.35
        if anchor_screen and c.get("screen_context") == anchor_screen:
            score += 0.22
        cand_sub = {_norm_token(v) for v in (c.get("scope_sub_tags") or [])}
        if anchor_sub and cand_sub and (anchor_sub & cand_sub):
            score += 0.10
        if _same_domain_family(c, anchor):
            score += 0.12
        txt = _normalize_step_text(str(c.get("step_text", "")))
        score += 0.28 * _overlap_ratio(context.get("search_text", ""), txt)
        score += 0.16 * _overlap_ratio(anchor_step, txt)
        if expected_terms and (_tokenize(txt) & expected_terms):
            score += 0.08
        return score

    best = max(cands, key=_rank)
    txt = _normalize_step_text(str(best.get("step_text", "")))
    if not txt:
        return None
    if _meaningful_overlap(context.get("search_text", ""), txt) < 0.08 and _meaningful_overlap(anchor_step, txt) < 0.08:
        return None
    return best


def _expected_outcome_terms(context: Optional[dict[str, Any]]) -> set[str]:
    if not context:
        return set()
    outcome = str(context.get("expected_outcome", "")).strip().lower()
    if not outcome:
        return set()
    return set(_EXPECTED_OUTCOME_TERMS.get(outcome, set())) or {token for token in re.findall(r"[a-z0-9]+", outcome) if token}


def _expected_outcome_bonus(hit: dict[str, Any], context: dict[str, Any]) -> float:
    expected_terms = _expected_outcome_terms(context)
    if not expected_terms:
        return 0.0
    local_then, local_and = _collect_local_assertions(hit.get("scenario_steps") or [], _find_anchor_index(hit, hit.get("scenario_steps") or []), context.get("search_text", ""), hit)
    blob = " ".join(
        part for part in (
            str(hit.get("scenario_title", "")),
            str(hit.get("step_text", "")),
            str(local_then or ""),
            str(local_and or ""),
        ) if part
    )
    tokens = _tokenize(blob)
    if tokens & expected_terms:
        return 0.32
    return 0.0


def _is_assertion_like(step_text: str) -> bool:
    tokens = _tokenize(step_text)
    if not tokens:
        return False
    if any(v in tokens for v in _ACTION_VERBS):
        return False
    return any(h in tokens for h in _ASSERTION_HINTS) or "should" in step_text.lower()


def _filter_optional_assertion(candidate: Optional[str], intent: str, anchor_text: str, then_text: str, context: Optional[dict[str, Any]] = None) -> Optional[str]:
    if not candidate:
        return None
    candidate = _normalize_step_text(candidate)
    if not candidate:
        return None
    then_text = _normalize_step_text(then_text)
    if candidate.lower() == then_text.lower() or not _is_assertion_like(candidate):
        return None

    if max(_overlap_ratio(intent, candidate), _overlap_ratio(anchor_text, candidate), _overlap_ratio(then_text, candidate)) >= 0.14:
        return candidate
    if context and (_tokenize(candidate) & _expected_outcome_terms(context)):
        return candidate
    return None


def _is_assertion_relevant(then_text: str, intent: str, anchor_text: str, context: Optional[dict[str, Any]] = None) -> bool:
    then_text = _normalize_step_text(then_text)
    if not then_text or not _is_assertion_like(then_text):
        return False
    if context and _has_specificity_conflict(then_text.lower(), context):
        return False
    expected_terms = _expected_outcome_terms(context)
    must_assert_terms = {
        term.lower()
        for term in ((context or {}).get("must_assert_terms") or [])
        if str(term).strip()
    }
    if _requires_strict_expected_terms(context):
        tokens = _tokenize(then_text)
        target_phrases = {
            str((context or {}).get("target_field") or "").strip().lower(),
            str((context or {}).get("entity") or "").strip().lower(),
        }
        signal_terms = {term for term in must_assert_terms if term and term not in target_phrases}
        has_expectation = bool((expected_terms and (tokens & expected_terms)) or any(term in then_text.lower() for term in signal_terms))
        target_terms = [
            str((context or {}).get("target_field") or "").strip(),
            str((context or {}).get("entity") or "").strip(),
        ]
        specific_target_terms = _specific_target_terms(" ".join(term for term in target_terms if term))
        if not specific_target_terms:
            has_target = True
        else:
            matched_specific = specific_target_terms & _tokenize(then_text)
            min_required = len(specific_target_terms) if len(specific_target_terms) <= 2 else len(specific_target_terms) - 1
            has_target = len(matched_specific) >= min_required
        return has_expectation and has_target
    if _meaningful_overlap(intent, then_text) >= 0.10:
        return True
    if _meaningful_overlap(anchor_text, then_text) >= 0.10:
        return True
    if expected_terms and (_tokenize(then_text) & expected_terms):
        return True
    words = {"success", "error", "failed", "display", "visible", "updated", "saved", "mandatory", "enabled", "disabled"}
    return any(w in _tokenize(then_text) for w in words)


def _requires_strict_expected_terms(context: Optional[dict[str, Any]]) -> bool:
    if not context:
        return False
    outcome = str(context.get("expected_outcome", "")).strip().lower()
    return outcome in _STRICT_ASSERTION_OUTCOMES


def _has_specificity_conflict(blob: str, context: dict[str, Any]) -> bool:
    blob_lower = blob.lower()
    context_text = " ".join(
        str(part or "")
        for part in (
            context.get("text"),
            context.get("search_text"),
            context.get("entity"),
            context.get("target_field"),
            " ".join(context.get("must_anchor_terms") or []),
        )
    ).lower()
    for candidate_markers, intent_markers in _SPECIFICITY_CONFLICTS:
        if any(marker in blob_lower for marker in candidate_markers) and not any(marker in context_text for marker in intent_markers):
            return True
    return False


def _specific_target_terms(text: str) -> set[str]:
    generic = {"application", "level", "decision", "field", "dropdown", "checkbox", "column", "list", "product", "products", "type", "stage"}
    return {token for token in _tokenize(text) if token not in generic}


def _build_scenario_title(intent: str, variant_idx: int, anchor: dict[str, Any]) -> str:
    base = intent.strip() or "Generated Scenario"
    if variant_idx <= 1:
        return base
    scen = str(anchor.get("scenario_title", "")).strip()
    if scen:
        return f"{base} [{scen[:48]}]"
    step = _normalize_step_text(str(anchor.get("step_text", "")))
    if step:
        return f"{base} [{step[:36]}]"
    return base


def _extract_placeholders(step_texts: list[str]) -> list[str]:
    out = []
    seen = set()
    skip = {"LogicalID", "ProductType", "ApplicationStage"}
    for text in step_texts:
        for p in _PLACEHOLDER_RE.findall(text or ""):
            key = p.strip()
            if not key or key in skip or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3}


def _domain_specific_terms(text: str) -> set[str]:
    generic = set(_INTENT_STOPWORDS) | {
        "move", "next", "stage", "credit", "approval", "recommendation", "application",
        "decision", "checkbox", "column", "field", "dropdown", "screen", "list", "product",
        "products", "type", "display", "enabled", "disabled", "checked", "unchecked",
        "recommended", "limit", "amount", "value", "validation", "save", "saved",
    }
    return {token for token in _tokenize(text) if token not in generic}


def _meaningful_terms(text: str) -> set[str]:
    return {t for t in _tokenize(text) if t not in _INTENT_STOPWORDS}


def _meaningful_overlap(a: str, b: str) -> float:
    ta = _meaningful_terms(a)
    tb = _meaningful_terms(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), 1)


def _overlap_ratio(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(min(len(ta), len(tb)), 1)


def _normalize_step_text(step_text: str) -> str:
    if not step_text:
        return ""
    lines = [ln.strip() for ln in str(step_text).replace("\r\n", "\n").split("\n")]
    primary = ""
    for ln in lines:
        if not ln or ln.startswith("|"):
            continue
        primary = ln
        break
    if not primary:
        primary = next((ln for ln in lines if ln), "")
    primary = re.sub(r"\s*###.*$", "", primary).strip()
    return re.sub(r"\s+", " ", primary).strip()


def _canonical_step_text(step_text: str) -> str:
    text = _normalize_step_text(step_text).lower()
    text = re.sub(r"<[^>]+>", "<var>", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _dedupe_steps(step_texts: list[str]) -> list[str]:
    out = []
    seen = set()
    for raw in step_texts:
        txt = _normalize_step_text(raw)
        key = _canonical_step_text(txt)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(txt)
    return out


def _fallback_given_step(flow_type: str) -> str:
    if flow_type == "ordered":
        return 'all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"'
    cands = search("all prerequisite are performed", top_k=5, keyword_filter="Given")
    if cands:
        return _normalize_step_text(str(cands[0].get("step_text", "")))
    return "all prerequisite are performed"


def _fallback_then_step(intent: Any, anchor: dict[str, Any]) -> str:
    context = None
    if isinstance(intent, dict):
        empty_scope = {"lob_scope": {"mode": "all", "values": []}, "stage_scope": {"mode": "all", "values": []}}
        context = _intent_anchor_context(intent, empty_scope, None)
        intent_text = context.get("search_text", context.get("text", ""))
    else:
        intent_text = str(intent or "").strip()

    anchor_bits = [
        str(anchor.get("step_text", "")),
        str(anchor.get("scenario_title", "")),
        str(anchor.get("screen_context", "")),
    ]
    query = " ".join(part for part in [intent_text, "expected result", *anchor_bits] if part).strip()
    screen_filter = str(anchor.get("screen_context", "") or "").strip() or None
    cands = [c for c in search(query, top_k=5, screen_filter=screen_filter, keyword_filter="Then") if _same_domain_family(c, anchor)]
    for cand in cands:
        txt = _normalize_step_text(str(cand.get("step_text", "")))
        if txt and _is_assertion_relevant(txt, intent_text, str(anchor.get("step_text", "")), context):
            return txt
    fallback = [c for c in search(intent_text, top_k=5, screen_filter=screen_filter, keyword_filter="Then") if _same_domain_family(c, anchor)]
    for cand in fallback:
        txt = _normalize_step_text(str(cand.get("step_text", "")))
        if txt and _is_assertion_relevant(txt, intent_text, str(anchor.get("step_text", "")), context):
            return txt
    generated = _generated_fallback_then(context, anchor)
    if generated:
        return generated
    return "expected behaviour should be observed"


def _generated_fallback_then(context: Optional[dict[str, Any]], anchor: dict[str, Any]) -> Optional[str]:
    if not context:
        return None
    target = str(context.get("target_field") or context.get("entity") or "expected field").strip()
    outcome = str(context.get("expected_outcome", "")).strip().lower()
    polarity = str(context.get("polarity", "")).strip().lower()
    if outcome == "checked":
        return f"{target} should be checked by default"
    if outcome == "disabled":
        return f"{target} should be disabled"
    if outcome == "enabled":
        return f"{target} should be enabled"
    if outcome == "display":
        return f"{target} should be displayed"
    if outcome == "state_change":
        stage_target = str(context.get("target_field") or anchor.get("scenario_title") or "next stage")
        return f"application should move to {stage_target}"
    if outcome == "validation_error":
        return "validation error should be displayed"
    if outcome == "derived_value":
        if polarity == "recommended":
            return f"{target} should be set to Recommended"
        if polarity == "not_recommended":
            return f"{target} should be set to Not Recommended"
        return f"{target} should reflect derived value"
    return None

def _render_feature(
    story: JiraStory,
    flow_type: str,
    template_text: str,
    scenario_plans: list[ScenarioPlan],
    story_scope_defaults: dict[str, Any],
    detected_stage: Optional[str],
    detected_sub_tags: list[str],
) -> str:
    tag_lines = _extract_top_template_tags(template_text, story, flow_type, detected_stage, detected_sub_tags)
    lines = []
    lines.extend(tag_lines)

    if flow_type == "unordered":
        dict_lines = _build_unordered_file_dict_lines(template_text, story_scope_defaults)
        if dict_lines:
            lines.append("")
            lines.extend(dict_lines)

    if lines:
        lines.append("")
    lines.append(f"Feature: {story.summary}")

    if flow_type == "unordered":
        bg = _extract_unordered_background(template_text)
        if bg:
            lines.append("")
            lines.extend(bg)

    current_section = None
    for idx, plan in enumerate(scenario_plans, 1):
        if plan.section != current_section:
            current_section = plan.section
            lines.append("")
            lines.extend(_render_section_header(current_section))
        lines.append("")
        lines.extend(_render_scenario_block(story, plan, flow_type, idx))

    return "\n".join(lines).rstrip() + "\n"


def _render_section_header(section: str) -> list[str]:
    return [
        "    #########################################################################################################",
        f"    ###### {section}",
        "    #########################################################################################################",
    ]


def _extract_top_template_tags(template_text: str, story: JiraStory, flow_type: str, detected_stage: Optional[str], detected_sub_tags: list[str]) -> list[str]:
    raw_tags = _extract_initial_template_tags(template_text)
    if not raw_tags:
        return []

    mapping = {
        "<EpicName>": story.issue_key.split("-")[0],
        "<AuthorName>": "CASForge",
        "<ImplementedBy>": "CASForge",
        "<ReviewedBy>": "CASForge",
        "<PrimaryModuleTag>": (detected_sub_tags[0].lstrip("@") if detected_sub_tags else "AppInfo"),
        "<OptionalReleaseTag>": (detected_stage.lstrip("@") if detected_stage else "Generated"),
        "<OptionalFlowTag>": ("OrderedFlow" if flow_type == "ordered" else "UnorderedFlow"),
        "<JIRA_ID>": story.issue_key,
        "<Feature Title>": story.summary,
    }

    out = []
    for line in raw_tags:
        rendered = line
        for key, value in mapping.items():
            rendered = rendered.replace(key, value)
        if _PLACEHOLDER_RE.search(rendered):
            continue
        out.append(rendered)
    return out


def _extract_initial_template_tags(template_text: str) -> list[str]:
    lines = template_text.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    tags = []
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            break
        if stripped.startswith("@"):
            tags.append(stripped)
            i += 1
            continue
        break
    return tags


def _build_unordered_file_dict_lines(template_text: str, story_scope_defaults: dict[str, Any]) -> list[str]:
    dmap = _extract_unordered_dict_map(template_text)
    lob_scope = story_scope_defaults.get("lob_scope", {"mode": "all", "values": []})
    stage_scope = story_scope_defaults.get("stage_scope", {"mode": "all", "values": []})
    if _is_specific_scope(lob_scope):
        dmap["ProductType"] = list(lob_scope.get("values") or [])
    if _is_specific_scope(stage_scope):
        dmap["ApplicationStage"] = list(stage_scope.get("values") or [])
    return _dict_lines_from_map(dmap)


def _extract_unordered_dict_map(template_text: str) -> dict[str, list[str]]:
    out = {}
    for line in template_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#${"):
            continue
        m = re.match(r"#\$\{\s*([^:}]+)\s*:\s*\[(.*?)\]\s*\}", stripped)
        if not m:
            continue
        key = m.group(1).strip()
        raw = m.group(2).strip()
        values = []
        for token in raw.split(","):
            text = token.strip().strip('"').strip("'")
            if text:
                values.append(text)
        out[key] = values
    return out


def _dict_lines_from_map(dmap: dict[str, list[str]]) -> list[str]:
    out = []
    for key, values in dmap.items():
        if not values:
            continue
        quoted = ",".join(f'"{v}"' for v in values)
        out.append(f"#${{{key}:[{quoted}]}}")
    return out


def _extract_unordered_background(template_text: str) -> list[str]:
    lines = template_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Background:"):
            start = i
            break
    if start is None:
        return []

    out = []
    for line in lines[start:]:
        if line.strip().startswith("Scenario Outline:"):
            break
        if not line.strip():
            if out:
                out.append("")
            continue
        out.append(line.rstrip())
    return out


def _render_scenario_block(story: JiraStory, plan: ScenarioPlan, flow_type: str, scenario_number: int) -> list[str]:
    lines = []
    indent = "    "
    step_indent = "        "

    if flow_type == "ordered":
        lines.append(f'{indent}Scenario Outline: For App with [ <LogicalID> ] {plan.title}')
    else:
        lines.append(f"{indent}Scenario Outline: {plan.title}")

    given = [s for s in plan.given_steps if s] or [_fallback_given_step(flow_type)]
    lines.append(f"{step_indent}Given {given[0]}")
    for step in given[1:]:
        lines.append(f"{step_indent}And {step}")

    when_steps = [s for s in plan.when_steps if s]
    if when_steps:
        lines.append(f"{step_indent}When {when_steps[0]}")
        for step in when_steps[1:]:
            lines.append(f"{step_indent}And {step}")

    lines.append(f"{step_indent}Then {plan.then_step}")
    if plan.then_and_step:
        lines.append(f"{step_indent}And {plan.then_and_step}")

    lines.append("")
    lines.extend(_scenario_level_dicts(plan, flow_type))

    if plan.tags:
        lines.append(f"{step_indent}{' '.join(plan.tags)}")

    lines.extend(_render_examples(story, plan, flow_type, scenario_number, step_indent))
    return lines


def _scenario_level_dicts(plan: ScenarioPlan, flow_type: str) -> list[str]:
    if flow_type != "unordered":
        return []
    lines = []
    lob = plan.effective_scope.get("lob_scope", {})
    stage = plan.effective_scope.get("stage_scope", {})
    if _is_specific_scope(lob):
        quoted = ",".join(f'"{v}"' for v in lob.get("values") or [])
        lines.append(f"        #${{ProductType:[{quoted}]}}")
    if _is_specific_scope(stage):
        quoted = ",".join(f'"{v}"' for v in stage.get("values") or [])
        lines.append(f"        #${{ApplicationStage:[{quoted}]}}")
    return lines


def _render_examples(story: JiraStory, plan: ScenarioPlan, flow_type: str, scenario_number: int, step_indent: str) -> list[str]:
    cols = ["LogicalID", "ProductType"] + plan.placeholders if flow_type == "ordered" else ["ProductType", "ApplicationStage"] + plan.placeholders
    if not cols:
        cols = ["col1"]

    values = []
    for col in cols:
        lc = col.lower()
        if flow_type == "ordered" and lc == "logicalid":
            values.append(f"{story.issue_key.replace('-', '_')}_{scenario_number:03d}")
            continue
        if lc == "producttype":
            lob = plan.effective_scope.get("lob_scope", {})
            if _is_specific_scope(lob) and len(lob.get("values") or []) == 1:
                values.append(str((lob.get("values") or ["<ProductType>"])[0]))
            else:
                values.append("<ProductType>")
            continue
        if lc == "applicationstage":
            stage = plan.effective_scope.get("stage_scope", {})
            if _is_specific_scope(stage) and len(stage.get("values") or []) == 1:
                values.append(str((stage.get("values") or ["<ApplicationStage>"])[0]))
            else:
                values.append("<ApplicationStage>")
            continue
        values.append(f"<{col}>")

    header = " | ".join(cols)
    row = " | ".join(values)
    return [
        f"{step_indent}Examples:",
        f"{step_indent}    | {header} |",
        f"{step_indent}    | {row} |",
    ]


def _ground_steps_to_repo(feature_text: str) -> tuple[str, list[dict[str, Any]], int, int]:
    lines = feature_text.splitlines()
    fixed = lines[:]
    unresolved = []
    total = 0
    grounded = 0
    existence_cache: dict[str, bool] = {}
    replacement_cache: dict[str, Optional[str]] = {}

    conn = get_conn()
    try:
        with get_cursor(conn) as cur:
            for i, line in enumerate(lines):
                m = _STEP_LINE.match(line)
                if not m:
                    continue
                total += 1
                indent, keyword, step_text = m.groups()
                canonical = _canonical_step_text(step_text)
                if _is_template_boilerplate(step_text):
                    grounded += 1
                    continue
                if canonical in existence_cache:
                    exists = existence_cache[canonical]
                else:
                    exists = _step_exists(cur, step_text)
                    existence_cache[canonical] = exists
                if exists:
                    grounded += 1
                    continue
                repl_key = f"{keyword.lower()}::{canonical}"
                if repl_key in replacement_cache:
                    repl = replacement_cache[repl_key]
                else:
                    repl = _best_replacement(step_text, keyword)
                    replacement_cache[repl_key] = repl
                if repl:
                    fixed[i] = f"{indent}{keyword} {repl}"
                    grounded += 1
                else:
                    unresolved.append({
                        "keyword": keyword,
                        "step_text": _normalize_step_text(step_text),
                        "line": i + 1,
                        "marker": "NEW_STEP_NOT_IN_REPO",
                    })
    finally:
        conn.close()

    text = "\n".join(fixed)
    if unresolved:
        text = _inject_new_step_notice(text, unresolved)
    text = _enforce_cas_format(text, None, [])
    return text, unresolved, total, grounded


def _inject_new_step_notice(feature_text: str, unresolved_steps: list[dict[str, Any]]) -> str:
    deduped = []
    seen = set()
    for item in unresolved_steps:
        key = f"{item.get('keyword','').lower()}::{_canonical_step_text(str(item.get('step_text','')))}"
        if not item.get("step_text") or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    lines = feature_text.splitlines()
    feature_idx = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("Feature:")), -1)
    if feature_idx < 0 or not deduped:
        return feature_text

    notice = ["", "    # CASForge notice: some steps were not found in repository and were generated."]
    for item in deduped[:20]:
        notice.append(f"    # [NEW_STEP_NOT_IN_REPO] {item['keyword']} {item['step_text']}")

    lines[feature_idx + 1:feature_idx + 1] = notice
    return "\n".join(lines)


def _is_template_boilerplate(step_text: str) -> bool:
    t = _canonical_step_text(step_text)
    return t in {
        _canonical_step_text('all prerequisite are performed in previous scenario of "<ProductType>" logical id "<LogicalID>"'),
        _canonical_step_text("user is on CAS Login Page"),
        _canonical_step_text('user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0'),
    }


def _step_exists(cur, step_text: str) -> bool:
    canonical = _canonical_step_text(step_text)
    if not canonical:
        return False

    # Fast path for already-normalized single-line repo-authentic steps.
    cur.execute(
        """
        SELECT 1
        FROM steps
        WHERE lower(trim(split_part(step_text, E'\n', 1))) = %s
           OR lower(trim(step_text)) = %s
        LIMIT 1
        """,
        (canonical, canonical),
    )
    if cur.fetchone() is not None:
        return True

    cur.execute(
        """
        SELECT 1
        FROM steps
        WHERE regexp_replace(
                regexp_replace(lower(trim(step_text)), '^(given|when|then|and|but)\s+', '', 'i'),
                '[[:space:]]+', ' ', 'g'
              ) = %s
           OR regexp_replace(
                regexp_replace(lower(trim(split_part(step_text, E'\n', 1))), '^(given|when|then|and|but)\s+', '', 'i'),
                '[[:space:]]+', ' ', 'g'
              ) = %s
        LIMIT 1
        """,
        (canonical, canonical),
    )
    return cur.fetchone() is not None


def _best_replacement(step_text: str, keyword: str) -> Optional[str]:
    by_kw = search(step_text, top_k=3, keyword_filter=keyword)
    best_kw = _best_replacement_candidate(step_text, by_kw, min_score=0.72)
    if best_kw:
        return best_kw
    any_hit = search(step_text, top_k=6)
    best_any = _best_replacement_candidate(step_text, any_hit, min_score=0.78)
    if best_any:
        return best_any
    return None


def _best_replacement_candidate(step_text: str, hits: list[dict[str, Any]], min_score: float) -> Optional[str]:
    source = _normalize_step_text(step_text)
    if not source or not hits:
        return None

    best_text = None
    best_score = 0.0
    for hit in hits:
        candidate = _normalize_step_text(str(hit.get("step_text", "")))
        if not candidate:
            continue
        seq = SequenceMatcher(None, source.lower(), candidate.lower()).ratio()
        overlap = max(_overlap_ratio(source, candidate), _meaningful_overlap(source, candidate))
        score = (seq * 0.65) + (overlap * 0.35)
        if score > best_score:
            best_score = score
            best_text = candidate
    if best_text and best_score >= min_score:
        return best_text
    return None


def _clean_output(raw: str, story: JiraStory) -> str:
    m = re.search(r"^Feature:", raw, re.MULTILINE)
    if not m:
        return f"Feature: {story.summary}\n\n{raw.strip()}"
    body = raw[m.start():]
    lines = body.splitlines()

    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if out and out[-1] != "":
                out.append("")
            continue
        if _is_gherkin_output_line(stripped):
            out.append(line.rstrip())
            continue
        break

    while out and out[-1] == "":
        out.pop()
    return "\n".join(out).rstrip()


def _is_gherkin_output_line(stripped_line: str) -> bool:
    return (
        stripped_line.startswith("Feature:")
        or stripped_line.startswith("Background:")
        or stripped_line.startswith("Scenario:")
        or stripped_line.startswith("Scenario Outline:")
        or stripped_line.startswith("Examples:")
        or stripped_line.startswith("@")
        or stripped_line.startswith("|")
        or stripped_line.startswith("#${")
        or stripped_line.startswith("Given ")
        or stripped_line.startswith("When ")
        or stripped_line.startswith("Then ")
        or stripped_line.startswith("And ")
        or stripped_line.startswith("But ")
        or stripped_line.startswith("#")
    )


def _enforce_cas_format(feature_text: str, stage_annotation: Optional[str], sub_tag_annotations: list[str]) -> str:
    lines = feature_text.splitlines()
    if not lines:
        return feature_text

    for i, line in enumerate(lines):
        if line.lstrip().startswith("Feature:"):
            lines[i] = re.sub(r"\s+@\w.*$", "", line).rstrip()
            break

    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)Scenario:\s*(.+)$", line)
        if m:
            lines[i] = f"{m.group(1)}Scenario Outline: {m.group(2)}"

    wanted_tags = [t for t in [stage_annotation, *sub_tag_annotations] if t]
    wanted_tag_text = " ".join(wanted_tags)

    scenario_idxs = [i for i, x in enumerate(lines) if x.lstrip().startswith("Scenario Outline:")]
    inserts: list[tuple[int, list[str]]] = []
    for s_i, start in enumerate(scenario_idxs):
        end = scenario_idxs[s_i + 1] if s_i + 1 < len(scenario_idxs) else len(lines)
        block = lines[start:end]
        if any(x.strip().startswith("Examples:") for x in block):
            continue
        scenario_indent = re.match(r"^(\s*)", lines[start]).group(1)
        step_indent = scenario_indent + "    "
        new_lines = [""]
        if wanted_tag_text:
            new_lines.append(step_indent + wanted_tag_text)
        new_lines.extend([
            step_indent + "Examples:",
            step_indent + "  | col1 |",
            step_indent + "  | val1 |",
        ])
        inserts.append((end, new_lines))

    for idx, new_lines in reversed(inserts):
        lines[idx:idx] = new_lines

    if wanted_tag_text:
        i = 0
        while i < len(lines):
            if not lines[i].strip().startswith("Examples:"):
                i += 1
                continue
            indent = re.match(r"^(\s*)", lines[i]).group(1)
            j = i - 1
            while j >= 0 and lines[j].strip() == "":
                j -= 1
            tag_line = f"{indent}{wanted_tag_text}"
            if j >= 0 and lines[j].strip().startswith("@"):
                lines[j] = tag_line
            else:
                lines.insert(i, tag_line)
                i += 1
            i += 1

    return "\n".join(lines).rstrip()














