"""
intent_extractor.py
-------------------
Single job: given a JiraStory, call LLM and return a list of test intents.

Each intent is a dict: {id, text, family}
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

from jinja2 import Template

from casforge.parsing.jira_parser import JiraStory
from casforge.generation import llm_client
from casforge.shared.paths import PROMPTS_DIR
from casforge.shared.settings import LLM_TEMPERATURE, LLM_MAX_TOKENS

_log = logging.getLogger(__name__)

_PROMPT_FILE = PROMPTS_DIR / "extract_intents.txt"

_FAMILY_ALIASES = {
    "core": "positive", "positive": "positive", "happy_path": "positive",
    "negative": "negative", "rejection": "negative",
    "validation": "validation", "mandatory": "validation",
    "dependency": "dependency", "dependent": "dependency",
    "state": "state_movement", "state_transition": "state_movement",
    "state_movement": "state_movement", "movement": "state_movement",
    "persistence": "persistence", "save": "persistence",
    "data_combination": "data_combination", "combination": "data_combination",
    "boundary": "data_combination", "edge": "edge",
}

_VALID_FAMILIES = {
    "positive", "negative", "validation", "dependency",
    "state_movement", "persistence", "data_combination", "edge",
}

_GENERIC_PATTERNS = ("system should work", "system should function", "works correctly", "as expected")

_SETUP_PREFIXES = (
    "user logs in", "user should be able to log in", "user should log in",
    "user navigates to", "user should be able to navigate", "user opens the screen",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_intents(
    story: JiraStory,
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Call LLM with extract_intents.txt and return structured intent list."""
    records = _call_extract_intents_llm(story)
    records = _normalise_records(records)
    records = _dedupe_records(records)
    for i, r in enumerate(records, 1):
        if not r.get("id"):
            r["id"] = f"intent_{i:03d}"
    _log.info("Extracted %d intents for %s", len(records), story.issue_key)
    return records


def coerce_intents(
    intents: Optional[list[Any]],
    story_scope_defaults: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Normalise intent objects from user input into canonical form."""
    if not intents:
        return []
    records: list[dict[str, Any]] = []
    for item in intents:
        if isinstance(item, str):
            records.append({"text": item.strip()})
        elif isinstance(item, dict) and item.get("text"):
            records.append(item)
        else:
            text = getattr(item, "text", None)
            if text:
                records.append({
                    "id": getattr(item, "id", None),
                    "text": str(text),
                    "family": getattr(item, "family", None),
                })
    records = _normalise_records(records)
    records = _dedupe_records(records)
    for i, r in enumerate(records, 1):
        if not r.get("id"):
            r["id"] = f"intent_{i:03d}"
    return records


def normalise_story_scope_defaults(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"lob_scope": {"mode": "all", "values": []}, "stage_scope": {"mode": "all", "values": []}}

    def _norm(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"mode": "all", "values": []}
        mode = str(value.get("mode", "all")).strip().lower()
        if mode not in {"all", "specific"}:
            mode = "all"
        values = [str(v).strip() for v in (value.get("values") or []) if str(v).strip()]
        return {"mode": mode, "values": list(dict.fromkeys(values))}

    return {"lob_scope": _norm(raw.get("lob_scope")), "stage_scope": _norm(raw.get("stage_scope"))}


def infer_story_scope_defaults(story: JiraStory) -> dict[str, Any]:
    return normalise_story_scope_defaults(None)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _load_prompt() -> tuple[str, str]:
    with open(_PROMPT_FILE, encoding="utf-8") as f:
        content = f.read()
    parts = content.split("\nUSER:\n", 1)
    if len(parts) != 2:
        raise ValueError(f"Prompt file {_PROMPT_FILE} must contain a 'USER:' section")
    system = parts[0].replace("SYSTEM:\n", "", 1).strip()
    return system, parts[1].strip()


def _call_extract_intents_llm(story: JiraStory) -> list[dict[str, Any]]:
    try:
        system_prompt, user_template = _load_prompt()

        def _blk(header: str, text: str, limit: int) -> str:
            t = (text or "").strip()[:limit]
            return f"{header}:\n{t}\n\n" if t else ""

        user_prompt = Template(user_template).render(
            key                      = story.issue_key,
            summary                  = story.summary,
            description              = (story.description or story.story_description or "").strip()[:1200],
            system_process_block     = _blk("System Process", story.system_process, 2000),
            business_scenarios_block = _blk("Business Scenarios / Exceptions", story.business_scenarios, 900),
            impacted_areas_block     = _blk("Impacted CAS Areas / Stages", story.impacted_areas, 500),
            key_ui_block             = _blk("Key UI Navigation", story.key_ui_steps, 500),
            acceptance_criteria_block= _blk("Acceptance Criteria", story.acceptance_criteria, 900),
            story_scope_block        = "",
        )
        raw = llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=min(LLM_TEMPERATURE, 0.15),
            max_tokens=max(640, min(LLM_MAX_TOKENS, 1400)),
        )
        return _parse_intent_records(raw)
    except Exception as exc:
        _log.error("Intent LLM extraction failed for %s: %s", story.issue_key, exc)
        return []


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _strip_wrappers(raw: str) -> str:
    text = (raw or "").strip()
    text = re.sub(r"```[a-z]*\s*", "", text).strip()
    return re.sub(r"```", "", text).strip()


def _parse_intent_records(raw: str) -> list[dict[str, Any]]:
    text = _strip_wrappers(raw)
    if not text:
        return []

    def _coerce(obj: Any) -> list[dict[str, Any]]:
        if not isinstance(obj, list):
            return []
        out = []
        for item in obj:
            if isinstance(item, str):
                out.append({"text": item})
            elif isinstance(item, dict):
                txt = item.get("text") or item.get("intent") or item.get("name")
                if txt:
                    out.append({"text": str(txt), "family": item.get("family")})
        return out

    try:
        recs = _coerce(json.loads(text))
        if recs:
            return recs
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            recs = _coerce(json.loads(re.sub(r",\s*\]", "]", m.group(0))))
            if recs:
                return recs
        except json.JSONDecodeError:
            pass

    return [{"text": t} for t in _parse_intents(raw)]


def _parse_intents(raw: str) -> list[str]:
    """Parse LLM output into a flat list of intent strings."""
    text = _strip_wrappers(raw)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(i).strip() for i in result if str(i).strip()]
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            result = json.loads(re.sub(r",\s*\]", "]", m.group(0)))
            if isinstance(result, list):
                return [str(i).strip() for i in result if str(i).strip()]
        except json.JSONDecodeError:
            pass

    items = re.findall(r'"([^"]{15,})"', text)
    if items:
        return items
    _log.warning("Could not parse intents from LLM output:\n%s", raw)
    return []


# ---------------------------------------------------------------------------
# Normalisation and deduplication
# ---------------------------------------------------------------------------

def _normalise_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        raw_text = str((rec or {}).get("text", "")).strip()
        if not raw_text:
            continue
        t = re.sub(r"\s+", " ", raw_text).strip()
        t = re.sub(r"^(user|system|the\s+\w+\s+screen)\s+should\s+be\s+able\s+to\s+", "", t, flags=re.I)
        t = re.sub(r"^(user|system|the\s+\w+\s+screen)\s+should\s+", "", t, flags=re.I)
        t = t.strip(" .-")
        if not t:
            continue
        t_low = t.lower()
        if any(t_low.startswith(p) for p in _SETUP_PREFIXES):
            continue
        if any(p in t_low for p in _GENERIC_PATTERNS) or len(re.findall(r"[a-z0-9]+", t_low)) < 4:
            continue
        family = _normalise_family((rec or {}).get("family"), t)
        out.append({"id": rec.get("id"), "text": t, "family": family})
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
        if any(SequenceMatcher(None, key, e["text"].lower()).ratio() >= 0.90 for e in out):
            continue
        seen.add(key)
        out.append({"id": rec.get("id"), "text": text, "family": rec.get("family", "positive")})
    return out


def _normalise_family(raw_family: Any, text: str) -> str:
    if raw_family is not None:
        key = str(raw_family).strip().lower().replace(" ", "_")
        fam = _FAMILY_ALIASES.get(key)
        if fam in _VALID_FAMILIES:
            return fam
    low = text.lower()
    for hints, fam in (
        ({"reject", "rejection", "error", "invalid", "not allow", "prevent", "fail", "failed"}, "negative"),
        ({"mandatory", "required", "validation", "validate", "field", "enable", "disable"}, "validation"),
        ({"depend", "linked", "sync", "propagate", "based on", "derived from"}, "dependency"),
        ({"save", "reopen", "persist", "retained", "retains"}, "persistence"),
        ({"move to next", "stage", "transition"}, "state_movement"),
        ({"combination", "boundary", "minimum", "maximum", "range", "multiple", "matrix"}, "data_combination"),
        ({"edge", "blank", "null", "zero", "duplicate"}, "edge"),
    ):
        if any(h in low for h in hints):
            return fam
    return "positive"
