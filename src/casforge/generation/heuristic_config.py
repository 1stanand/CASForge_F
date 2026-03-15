from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from typing import Any

from casforge.shared.paths import GENERATION_ASSETS_DIR

_log = logging.getLogger(__name__)

DOMAIN_KNOWLEDGE_PATH = GENERATION_ASSETS_DIR / "domain_knowledge.json"
PLANNER_HINTS_PATH = GENERATION_ASSETS_DIR / "planner_hints.json"
ASSEMBLER_HINTS_PATH = GENERATION_ASSETS_DIR / "assembler_hints.json"

_DISALLOWED_KEYS = {
    "emit",
    "condition",
    "effect",
    "polarity",
    "family_hint",
    "title",
    "screen_hint",
    "query",
}

_DOMAIN_KEYS = {
    "lob_aliases",
    "entities",
    "stages",
    "families",
    "sections",
    "matrix_terms",
    "state_transition_terms",
}

_PLANNER_KEYS = {
    "target_aliases",
    "synthetic_entity_blocklist",
    "synthetic_templates",
}

_ASSEMBLER_KEYS = {
    "specificity_conflicts",
    "family_terms",
    "section_terms",
    "matrix_terms",
    "path_domain_stopwords",
}


def load_domain_knowledge() -> dict[str, Any]:
    return copy.deepcopy(_load_domain_knowledge())


def load_planner_hints() -> dict[str, Any]:
    return copy.deepcopy(_load_planner_hints())


def load_assembler_hints() -> dict[str, Any]:
    return copy.deepcopy(_load_assembler_hints())


def reload_heuristic_configs() -> None:
    _load_domain_knowledge.cache_clear()
    _load_planner_hints.cache_clear()
    _load_assembler_hints.cache_clear()


@lru_cache(maxsize=1)
def _load_domain_knowledge() -> dict[str, Any]:
    return _load_config(
        path=DOMAIN_KNOWLEDGE_PATH,
        name="domain_knowledge",
        allowed_keys=_DOMAIN_KEYS,
        defaults=_default_domain_knowledge(),
        normalizer=_normalise_domain_knowledge,
    )


@lru_cache(maxsize=1)
def _load_planner_hints() -> dict[str, Any]:
    return _load_config(
        path=PLANNER_HINTS_PATH,
        name="planner_hints",
        allowed_keys=_PLANNER_KEYS,
        defaults=_default_planner_hints(),
        normalizer=_normalise_planner_hints,
    )


@lru_cache(maxsize=1)
def _load_assembler_hints() -> dict[str, Any]:
    return _load_config(
        path=ASSEMBLER_HINTS_PATH,
        name="assembler_hints",
        allowed_keys=_ASSEMBLER_KEYS,
        defaults=_default_assembler_hints(),
        normalizer=_normalise_assembler_hints,
    )


def _load_config(
    *,
    path,
    name: str,
    allowed_keys: set[str],
    defaults: dict[str, Any],
    normalizer,
) -> dict[str, Any]:
    try:
        raw_text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        _log.warning("CASForge heuristic config missing: %s", path)
        return copy.deepcopy(defaults)
    except OSError as exc:
        _log.warning("CASForge heuristic config unreadable: %s (%s)", path, exc)
        return copy.deepcopy(defaults)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _log.warning("CASForge heuristic config invalid JSON: %s (%s)", path, exc)
        return copy.deepcopy(defaults)

    if not isinstance(parsed, dict):
        _log.warning("CASForge heuristic config must be a JSON object: %s", path)
        return copy.deepcopy(defaults)

    unknown = sorted(set(parsed) - allowed_keys)
    if unknown:
        _log.warning("%s config contains unsupported keys %s; ignoring file", name, ", ".join(unknown))
        return copy.deepcopy(defaults)

    disallowed_path = _find_disallowed_key_path(parsed)
    if disallowed_path:
        _log.warning("%s config contains disallowed rule-like key at %s; ignoring file", name, disallowed_path)
        return copy.deepcopy(defaults)

    return normalizer(parsed, defaults, name)


def _find_disallowed_key_path(value: Any, path: str = "root") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _DISALLOWED_KEYS:
                return f"{path}.{key}"
            nested_path = _find_disallowed_key_path(nested, f"{path}.{key}")
            if nested_path:
                return nested_path
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested_path = _find_disallowed_key_path(item, f"{path}[{index}]")
            if nested_path:
                return nested_path
    return None


def _default_domain_knowledge() -> dict[str, Any]:
    return {
        "lob_aliases": {},
        "entities": tuple(),
        "stages": tuple(),
        "families": {},
        "sections": {},
        "matrix_terms": {},
        "state_transition_terms": tuple(),
    }


def _default_planner_hints() -> dict[str, Any]:
    return {
        "target_aliases": tuple(),
        "synthetic_entity_blocklist": set(),
        "synthetic_templates": {},
    }


def _default_assembler_hints() -> dict[str, Any]:
    return {
        "specificity_conflicts": tuple(),
        "family_terms": {},
        "section_terms": {},
        "matrix_terms": {},
        "path_domain_stopwords": set(),
    }


def _normalise_domain_knowledge(raw: dict[str, Any], defaults: dict[str, Any], name: str) -> dict[str, Any]:
    result = copy.deepcopy(defaults)
    result["lob_aliases"] = _normalise_alias_map(
        raw.get("lob_aliases"),
        section="lob_aliases",
        name=name,
        key_field="canonical",
        list_field="phrases",
    )
    result["entities"] = _normalise_structured_entries(
        raw.get("entities"),
        section="entities",
        name=name,
        required={"canonical", "aliases"},
        allowed={"canonical", "aliases", "family", "screens"},
        normalizer=_normalise_entity_entry,
    )
    result["stages"] = _normalise_structured_entries(
        raw.get("stages"),
        section="stages",
        name=name,
        required={"canonical", "aliases"},
        allowed={"canonical", "aliases"},
        normalizer=_normalise_stage_entry,
    )
    result["families"] = _normalise_term_map(
        raw.get("families"),
        section="families",
        name=name,
        key_field="key",
        allowed={"key", "terms"},
    )
    result["sections"] = _normalise_section_map(raw.get("sections"), name=name)
    result["matrix_terms"] = _normalise_term_map(
        raw.get("matrix_terms"),
        section="matrix_terms",
        name=name,
        key_field="key",
        allowed={"key", "terms"},
    )
    result["state_transition_terms"] = tuple(_normalise_string_list(raw.get("state_transition_terms")))
    return result


def _normalise_planner_hints(raw: dict[str, Any], defaults: dict[str, Any], name: str) -> dict[str, Any]:
    result = copy.deepcopy(defaults)
    result["target_aliases"] = _normalise_structured_entries(
        raw.get("target_aliases"),
        section="target_aliases",
        name=name,
        required={"match", "canonical", "scope"},
        allowed={"match", "canonical", "scope"},
        normalizer=_normalise_target_alias_entry,
    )
    result["synthetic_entity_blocklist"] = set(_normalise_string_list(raw.get("synthetic_entity_blocklist")))
    result["synthetic_templates"] = _normalise_template_map(raw.get("synthetic_templates"), name=name)
    return result


def _normalise_assembler_hints(raw: dict[str, Any], defaults: dict[str, Any], name: str) -> dict[str, Any]:
    result = copy.deepcopy(defaults)
    result["specificity_conflicts"] = _normalise_structured_entries(
        raw.get("specificity_conflicts"),
        section="specificity_conflicts",
        name=name,
        required={"candidate_markers", "intent_markers"},
        allowed={"candidate_markers", "intent_markers"},
        normalizer=_normalise_specificity_conflict,
    )
    result["family_terms"] = _normalise_term_bucket_map(raw.get("family_terms"), section="family_terms", name=name)
    result["section_terms"] = _normalise_term_bucket_map(raw.get("section_terms"), section="section_terms", name=name)
    result["matrix_terms"] = _normalise_term_bucket_map(raw.get("matrix_terms"), section="matrix_terms", name=name)
    result["path_domain_stopwords"] = set(_normalise_string_list(raw.get("path_domain_stopwords")))
    return result


def _normalise_alias_map(
    raw: Any,
    *,
    section: str,
    name: str,
    key_field: str,
    list_field: str,
) -> dict[str, tuple[str, ...]]:
    entries = _normalise_structured_entries(
        raw,
        section=section,
        name=name,
        required={key_field, list_field},
        allowed={key_field, list_field},
        normalizer=lambda value: {
            "key": _clean_text(value.get(key_field)),
            "terms": tuple(_normalise_string_list(value.get(list_field))),
        },
    )
    return {
        entry["key"]: entry["terms"]
        for entry in entries
        if entry["key"] and entry["terms"]
    }


def _normalise_term_map(
    raw: Any,
    *,
    section: str,
    name: str,
    key_field: str,
    allowed: set[str],
) -> dict[str, tuple[str, ...]]:
    entries = _normalise_structured_entries(
        raw,
        section=section,
        name=name,
        required={key_field, "terms"},
        allowed=allowed,
        normalizer=lambda value: {
            "key": _clean_text(value.get(key_field)),
            "terms": tuple(_normalise_string_list(value.get("terms"))),
        },
    )
    return {
        entry["key"]: entry["terms"]
        for entry in entries
        if entry["key"] and entry["terms"]
    }


def _normalise_section_map(raw: Any, *, name: str) -> dict[str, dict[str, Any]]:
    entries = _normalise_structured_entries(
        raw,
        section="sections",
        name=name,
        required={"key", "display_name", "terms"},
        allowed={"key", "display_name", "terms"},
        normalizer=lambda value: {
            "key": _clean_text(value.get("key")),
            "display_name": _clean_text(value.get("display_name")),
            "terms": tuple(_normalise_string_list(value.get("terms"))),
        },
    )
    return {
        entry["key"]: {
            "display_name": entry["display_name"],
            "terms": entry["terms"],
        }
        for entry in entries
        if entry["key"] and entry["display_name"] and entry["terms"]
    }


def _normalise_term_bucket_map(raw: Any, *, section: str, name: str) -> dict[str, set[str]]:
    if not isinstance(raw, dict):
        if raw is not None:
            _log.warning("%s config section %s must be an object; ignoring section", name, section)
        return {}
    out: dict[str, set[str]] = {}
    for key, value in raw.items():
        clean_key = _clean_text(key)
        if not clean_key:
            _log.warning("%s config section %s contains an empty key; ignoring entry", name, section)
            continue
        out[clean_key] = set(_normalise_string_list(value))
    return {key: value for key, value in out.items() if value}


def _normalise_template_map(raw: Any, *, name: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        if raw is not None:
            _log.warning("%s config section synthetic_templates must be an object; ignoring section", name)
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for key, value in raw.items():
        clean_key = _clean_text(key)
        if not clean_key:
            _log.warning("%s config section synthetic_templates contains an empty key; ignoring entry", name)
            continue
        templates = []
        for item in value if isinstance(value, list) else []:
            text = _clean_text(item)
            if not text:
                continue
            if "{target}" not in text:
                _log.warning("%s synthetic template %s must include {target}; skipping template", name, clean_key)
                continue
            templates.append(text)
        if templates:
            out[clean_key] = tuple(templates)
    return out


def _normalise_structured_entries(
    raw: Any,
    *,
    section: str,
    name: str,
    required: set[str],
    allowed: set[str],
    normalizer,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        if raw is not None:
            _log.warning("%s config section %s must be a list; ignoring section", name, section)
        return tuple()
    out = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            _log.warning("%s config section %s[%d] must be an object; skipping entry", name, section, index)
            continue
        unknown = set(item) - allowed
        missing = required - set(item)
        if unknown or missing:
            _log.warning(
                "%s config section %s[%d] has unsupported keys %s or missing keys %s; skipping entry",
                name,
                section,
                index,
                sorted(unknown),
                sorted(missing),
            )
            continue
        normalised = normalizer(item)
        if normalised:
            out.append(normalised)
    return tuple(out)


def _normalise_entity_entry(value: dict[str, Any]) -> dict[str, Any] | None:
    canonical = _clean_text(value.get("canonical"))
    aliases = tuple(_normalise_string_list(value.get("aliases")))
    if not canonical or not aliases:
        return None
    return {
        "canonical": canonical,
        "aliases": aliases,
        "family": _clean_text(value.get("family")),
        "screens": tuple(_normalise_string_list(value.get("screens"))),
    }


def _normalise_stage_entry(value: dict[str, Any]) -> dict[str, Any] | None:
    canonical = _clean_text(value.get("canonical"))
    aliases = tuple(_normalise_string_list(value.get("aliases")))
    if not canonical or not aliases:
        return None
    return {"canonical": canonical, "aliases": aliases}


def _normalise_target_alias_entry(value: dict[str, Any]) -> dict[str, Any] | None:
    match = _clean_text(value.get("match"))
    canonical = _clean_text(value.get("canonical"))
    scope = _clean_text(value.get("scope")).lower()
    if not match or not canonical or scope not in {"global", "planner"}:
        return None
    return {"match": match, "canonical": canonical, "scope": scope}


def _normalise_specificity_conflict(value: dict[str, Any]) -> dict[str, Any] | None:
    candidate_markers = tuple(_normalise_string_list(value.get("candidate_markers")))
    intent_markers = tuple(_normalise_string_list(value.get("intent_markers")))
    if not candidate_markers or not intent_markers:
        return None
    return {
        "candidate_markers": candidate_markers,
        "intent_markers": intent_markers,
    }


def _normalise_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen = set()
    for item in raw:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
