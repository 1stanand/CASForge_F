"""
generation/forge.py
-------------------
Assembly pipeline: retrieval → LLM scenario selection → intermediate JSON → .feature file.

forge_feature(story, intents, flow_type, on_progress=None) -> ForgeResult

Phase A — LLM (per intent):
  1. search(query=intent_text, top_k=20)
  2. Gate: skip only if no results OR all scores < _MIN_RETRIEVAL_SCORE
  3. Group results into top 5 unique scenarios
  4. Single LLM call: pick best scenario + output pruned steps (pick_scenario.txt)
  5. Save to intermediate JSON (output/{key}_scenarios.json) after all intents

Phase B — Assembly (deterministic):
  6. Read scenarios from intermediate result
  7. Apply ordered or unordered template:
       ordered   → @Order, no Background, no #${}, LogicalID prerequisite step
       unordered → Background login, #${} dicts, plain scenario titles
  8. Build Examples tables (from retrieved example_blocks + <Variable> scan)
  9. Grounding check: steps not in repo get # [NEW_STEP_NOT_IN_REPO]
  10. Return ForgeResult
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from jinja2 import Template

from casforge.parsing.jira_parser import JiraStory
from casforge.retrieval.retrieval import search
from casforge.generation import llm_client
from casforge.shared.paths import PROMPTS_DIR
from casforge.shared.settings import LLM_TEMPERATURE, LLM_MAX_TOKENS, OUTPUT_DIR
from casforge.storage.connection import get_conn, release_conn, get_cursor
from casforge.workflow.ordering import detect_stage

_log = logging.getLogger(__name__)

_PROMPT_FILE  = PROMPTS_DIR / "pick_scenario.txt"
_TEMPLATES_DIR = PROMPTS_DIR.parent / "templates"

_MIN_RETRIEVAL_SCORE = 0.25

# Login steps — kept in ordered scenarios, stripped from unordered (Background handles them)
_LOGIN_STEPS_LOWER: set[str] = {
    "user is on cas login page",
    'user logged in cas with valid username and password present in "logindetailscas.xlsx" under "logindata" and 0',
}

# Prerequisite step injected as first Given in every ordered scenario
_PREREQ_STEP = ('all prerequisite are performed in previous scenario'
                ' of "<ProductType>" logical id "<LogicalID>"')


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ForgeResult:
    feature_text: str
    quality: dict             = field(default_factory=dict)
    unresolved_steps: list    = field(default_factory=list)
    omitted_plan_items: list  = field(default_factory=list)
    coverage_gaps: list       = field(default_factory=list)
    scenario_debug: list      = field(default_factory=list)
    scenarios_json_path: str  = ""


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def _load_prompt() -> tuple[str, str]:
    with open(_PROMPT_FILE, encoding="utf-8") as f:
        content = f.read()
    parts = content.split("\nUSER:\n", 1)
    if len(parts) != 2:
        raise ValueError(f"{_PROMPT_FILE} must have a 'USER:' section")
    system = parts[0].replace("SYSTEM:\n", "", 1).strip()
    return system, parts[1].strip()


# ---------------------------------------------------------------------------
# Template parsing
# ---------------------------------------------------------------------------

def _read_template(flow_type: str) -> str:
    fname = "ordered.feature" if flow_type == "ordered" else "unordered.feature"
    path = _TEMPLATES_DIR / fname
    with open(path, encoding="utf-8") as f:
        return f.read()


def _build_header_tags(story: JiraStory, flow_type: str) -> list[str]:
    """
    Extract @Tag lines from the template and fill in real values.
    Skips truly optional placeholder tags that have no real value.
    """
    template = _read_template(flow_type)
    tags: list[str] = []
    for line in template.splitlines():
        stripped = line.strip()
        if stripped.startswith("Feature:"):
            break
        if not stripped.startswith("@"):
            continue

        # Fill known placeholders
        filled = (stripped
                  .replace("<EpicName>",        "CAS")
                  .replace("<AuthorName>",       "CASForge")
                  .replace("<ImplementedBy>",    "CASForge")
                  .replace("<ReviewedBy>",       "CASForge")
                  .replace("<JIRA_ID>",          story.issue_key))

        # Replace any remaining angle-bracket placeholder with a derived value
        filled = re.sub(r"@<PrimaryModuleTag>",  "@CASForge", filled)
        filled = re.sub(r"@<Optional\w+>",       "",          filled)
        filled = re.sub(r"@<\w+>",               "",          filled)
        filled = filled.strip()

        if filled:
            tags.append(filled)

    return tags


def _extract_dict_lines(template: str) -> list[str]:
    """Pull #${...} dictionary lines from the template."""
    return [l.strip() for l in template.splitlines()
            if l.strip().startswith("#${")]


def _template_has_background(template: str) -> bool:
    return "Background:" in template


# ---------------------------------------------------------------------------
# Scenario grouping
# ---------------------------------------------------------------------------

def _group_by_scenario(results: list[dict]) -> list[dict]:
    """Group step results by parent scenario. Returns top 5 unique scenarios."""
    seen: dict[tuple, dict] = {}
    for r in results:
        key = (r.get("scenario_title") or "", r.get("file_name") or "")
        score = r.get("score", 0.0)
        if key not in seen:
            seen[key] = {
                "scenario_title":  r.get("scenario_title") or "",
                "file_name":       r.get("file_name") or "",
                "scenario_steps":  r.get("scenario_steps") or [],
                "example_blocks":  r.get("example_blocks") or [],
                "_score":          score,
            }
        else:
            seen[key]["_score"] = max(seen[key]["_score"], score)

    return sorted(seen.values(), key=lambda x: -x["_score"])[:5]


# ---------------------------------------------------------------------------
# Scenario list formatter (for LLM prompt)
# ---------------------------------------------------------------------------

def _format_scenario_list(unique_scenarios: list[dict]) -> str:
    """Title + first 6 steps per candidate, numbered."""
    parts = []
    for i, scen in enumerate(unique_scenarios, 1):
        title = scen["scenario_title"] or "(untitled)"
        fname = scen["file_name"] or ""
        steps = scen["scenario_steps"][:6]
        lines = [f"{i}. [{fname}] {title}"]
        for s in steps:
            kw   = s.get("keyword", "Given")
            text = s.get("step_text", "")
            lines.append(f"   {kw} {text}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM call: pick best scenario + prune steps (combined)
# ---------------------------------------------------------------------------

def _llm_pick_and_prune(
    intent: dict,
    story: JiraStory,
    unique_scenarios: list[dict],
) -> list[tuple[str, str]]:
    """
    Single LLM call. Returns (keyword, step_text) list.
    """
    system_prompt, user_template = _load_prompt()
    user_prompt = Template(user_template).render(
        intent_text    = intent.get("text", ""),
        family         = intent.get("family", "positive"),
        story_key      = story.issue_key,
        story_summary  = story.summary,
        system_process = (story.system_process or "")[:600],
        scenario_list  = _format_scenario_list(unique_scenarios),
    )
    raw = llm_client.chat(
        system_prompt = system_prompt,
        user_prompt   = user_prompt,
        temperature   = min(LLM_TEMPERATURE, 0.1),
        max_tokens    = 512,
    )
    return _parse_gwt_lines(raw)


# ---------------------------------------------------------------------------
# Step line parser
# ---------------------------------------------------------------------------

def _parse_gwt_lines(raw: str) -> list[tuple[str, str]]:
    """Parse LLM output into ordered list of (keyword, step_text) tuples."""
    steps: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lower = line.lower()

        if re.match(r"^given\s", lower, re.I):
            if text := line[6:].strip():
                steps.append(("Given", text))
        elif re.match(r"^when\s", lower, re.I):
            if text := line[5:].strip():
                steps.append(("When", text))
        elif re.match(r"^then\s", lower, re.I):
            if text := line[5:].strip():
                steps.append(("Then", text))
        elif re.match(r"^and\s", lower, re.I):
            if text := line[4:].strip():
                steps.append(("And", text))
        elif re.match(r"^but\s", lower, re.I):
            if text := line[4:].strip():
                steps.append(("But", text))

    return steps


# ---------------------------------------------------------------------------
# Intermediate JSON (Step 10)
# ---------------------------------------------------------------------------

def _save_scenarios_json(story: JiraStory, scenarios: list[dict], omitted: list[dict]) -> str:
    """
    Save LLM-processed scenarios to JSON before assembly.
    Returns the file path.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_key = story.issue_key.replace("-", "_")
    path = os.path.join(OUTPUT_DIR, f"{safe_key}_scenarios.json")

    payload = {
        "story_key":      story.issue_key,
        "story_summary":  story.summary,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(scenarios),
        "scenarios": [
            {
                "intent_id":             s["intent"].get("id", ""),
                "intent_text":           s["intent"].get("text", ""),
                "family":                s["intent"].get("family", "positive"),
                "steps":                 [{"keyword": kw, "step_text": st} for kw, st in s["steps"]],
                "example_blocks":        s["example_blocks"],
                "source_scenario_title": s.get("source_scenario_title", ""),
                "source_file":           s.get("source_file", ""),
            }
            for s in scenarios
        ],
        "omitted": omitted,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    _log.info("Scenarios saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# Canonical normalization helpers
# ---------------------------------------------------------------------------

_QUOTED_RE   = re.compile(r'"[^"]*"')
_VARIABLE_RE = re.compile(r'<[^>]+>')


def _canonicalize(step_text: str) -> str:
    """Normalize a step to its pattern form for fuzzy grounding comparison.

    Both "quoted literals" and <Variables> are collapsed to the token <param>,
    so 'user opens app of "HL"' and 'user opens app of "<ProductType>"' and
    'user opens app of <ProductType>' all produce the same canonical string.
    """
    s = step_text.lower().strip()
    s = _QUOTED_RE.sub("<param>", s)
    s = _VARIABLE_RE.sub("<param>", s)
    return s


# ---------------------------------------------------------------------------
# Post-processing literalizer
# ---------------------------------------------------------------------------

def _literalize_steps(
    steps: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Replace "quoted literal" values in steps with <ParamN> placeholders.

    Rules:
    - Only plain "literal" strings are replaced; "< Variable >" strings (already
      parameterized) are left untouched — pattern matches '"[^"<>]*"'.
    - The counter is scenario-scoped (reset each call).
    - The same literal value across multiple steps in the same scenario reuses
      the same <ParamN> name (deduplicated via `seen`).

    Returns:
        cleaned_steps  — list of (keyword, step_text) with literals replaced
        new_param_cols — list of new column names (Param1, Param2, …) in order
                         of first appearance; caller appends these to Examples.
    """
    seen: dict[str, str] = {}
    counter = 0
    new_cols: list[str] = []

    def _replace(m: re.Match) -> str:
        nonlocal counter
        val = m.group(0)   # full match including quotes, e.g. '"Credit Card"'
        if val not in seen:
            counter += 1
            name = f"Param{counter}"
            seen[val] = name
            new_cols.append(name)
        return f"<{seen[val]}>"

    _plain_literal = re.compile(r'"[^"<>]*"')
    cleaned: list[tuple[str, str]] = []
    for kw, text in steps:
        new_text = _plain_literal.sub(_replace, text)
        cleaned.append((kw, new_text))
    return cleaned, new_cols


# ---------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------

def _load_known_steps() -> tuple[set[str], set[str]]:
    """Load corpus steps from DB.

    Returns:
        exact     — set of lower(trim(step_text)) for exact-match grounding
        canonical — set of _canonicalize(s) for fuzzy pattern-match grounding
                    (same literal → same <param>, so "HL" matches "<ProductType>")
    No DB schema change or re-ingest needed; canonical set is derived in Python.
    """
    conn = get_conn()
    try:
        with get_cursor(conn) as cur:
            cur.execute("SELECT DISTINCT lower(trim(step_text)) AS s FROM steps")
            exact = {row["s"] for row in cur.fetchall() if row["s"]}
        canonical = {_canonicalize(s) for s in exact}
        return exact, canonical
    except Exception as e:
        _log.warning("Could not load known steps: %s", e)
        return set(), set()
    finally:
        release_conn(conn)


# ---------------------------------------------------------------------------
# Scope collector (for #${} dict lines)
# ---------------------------------------------------------------------------

def _collect_scope(all_results: list[dict]) -> tuple[list[str], list[str]]:
    product_types: list[str] = []
    app_stages: list[str]    = []
    seen_pt: set[str]        = set()
    seen_as: set[str]        = set()

    for r in all_results:
        for pt in (r.get("scope_product_types") or []):
            if pt.lower() not in seen_pt:
                seen_pt.add(pt.lower()); product_types.append(pt)
        for st in (r.get("scope_application_stages") or []):
            if st.lower() not in seen_as:
                seen_as.add(st.lower()); app_stages.append(st)

    return product_types[:6], app_stages[:6]


# ---------------------------------------------------------------------------
# Feature file builder — header
# ---------------------------------------------------------------------------

def _build_file_header(
    story: JiraStory,
    flow_type: str,
    product_types: list[str],
    app_stages: list[str],
) -> str:
    template = _read_template(flow_type)
    tags = _build_header_tags(story, flow_type)
    lines: list[str] = list(tags) + [""]

    if flow_type == "unordered":
        # Dictionary comment lines: only include scope values mentioned in the story text.
        # Using retrieval-derived scope leads to unrelated product types from other stories.
        # Emit empty brackets when scope cannot be reliably determined from the story itself.
        dict_lines = _extract_dict_lines(template)
        if dict_lines:
            story_text = f"{story.summary} {story.system_process or ''}".lower()
            trusted_pt = [v for v in product_types if v.lower() in story_text]
            trusted_as = [v for v in app_stages if v.lower() in story_text]
            pt_val = ", ".join(f'"{v}"' for v in trusted_pt)
            as_val = ", ".join(f'"{v}"' for v in trusted_as)
            lines.append(f'#${{ProductType:[{pt_val}]}}')
            lines.append(f'#${{ApplicationStage:[{as_val}]}}')
        lines.append("")

    lines.append(f"Feature: {story.summary}")
    lines.append("")

    if flow_type == "unordered" and _template_has_background(template):
        lines += [
            "    Background:",
            "        Given user is on CAS Login Page",
            '        And user logged in CAS with valid username and password present in "LoginDetailsCAS.xlsx" under "LoginData" and 0',
            "",
        ]

    if flow_type == "ordered":
        # Business context block
        lines += [
            "    " + "#" * 105,
            "    ###### BUSINESS CONTEXT",
            "    ###### " + "-" * 98,
            f"    ###### {story.issue_key}: {story.summary}",
        ]
        context = (story.system_process or story.description or "").strip()
        for bullet in context.splitlines()[:3]:
            b = bullet.strip()
            if b:
                lines.append(f"    ######   - {b[:100]}")
        lines.append("    " + "#" * 105)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature file builder — scenario
# ---------------------------------------------------------------------------

def _build_examples_table(
    steps: list[tuple[str, str]],
    example_blocks: list[dict],
    flow_type: str,
    logical_id: str,
    extra_cols: list[str] | None = None,
) -> Optional[str]:
    """
    Build Examples table.
    Ordered:   LogicalID + ProductType always first, then step variables.
    Unordered: ProductType + ApplicationStage from example_blocks, then step variables.
    extra_cols: additional ParamN columns produced by _literalize_steps() — appended at
                the end with placeholder row values for the tester to fill in.
    Returns formatted table string, or None if nothing to show.
    """
    extra_cols = extra_cols or []

    # Collect <Variable> patterns from actual pruned steps
    step_vars: list[str] = []
    seen_step_vars: set[str] = set()
    for _, step_text in steps:
        for ph in re.findall(r"<([^>]+)>", step_text):
            if ph.lower() not in seen_step_vars:
                seen_step_vars.add(ph.lower())
                step_vars.append(ph)

    # Only use example_block columns that appear in actual step variables
    # (prevents importing unrelated columns from a different scenario's Examples)
    eb_rows: list[dict] = []
    if example_blocks and step_vars:
        first = example_blocks[0]
        raw_rows = (first.get("rows") or [])[:2]
        eb_rows = raw_rows

    if flow_type == "ordered":
        # Always: LogicalID, ProductType first, then any other step variables
        seen_base = {"logicalid", "producttype"}
        other = [c for c in step_vars if c.lower() not in seen_base]
        all_headers = ["LogicalID", "ProductType"] + other
        row_vals = [logical_id, "<ProductType>"] + [f"<{c}>" for c in other]
    else:
        # Unordered: step variables in order, with real data from EB rows if available
        all_headers = step_vars if step_vars else ["ProductType"]
        if eb_rows:
            row_vals = [str(eb_rows[0].get(h) or eb_rows[0].get(h.lower()) or f"<{h}>")
                        for h in all_headers]
        else:
            row_vals = [f"<{h}>" for h in all_headers]

    # Append literalizer-derived ParamN columns (tester fills in row values)
    seen_headers_lower = {h.lower() for h in all_headers}
    for col in extra_cols:
        if col.lower() not in seen_headers_lower:
            all_headers.append(col)
            row_vals.append(f"<{col}>")
            seen_headers_lower.add(col.lower())

    if not all_headers:
        return None

    # Column widths
    col_w = {h: max(len(h), len(v)) for h, v in zip(all_headers, row_vals)}

    def _fmt_row(values: list[str]) -> str:
        cells = [v.ljust(col_w[h]) for h, v in zip(all_headers, values)]
        return "            | " + " | ".join(cells) + " |"

    return "\n".join([
        "",
        "        Examples:",
        _fmt_row(all_headers),
        _fmt_row(row_vals),
    ])


def _build_scenario(
    intent: dict,
    idx: int,
    raw_steps: list[tuple[str, str]],
    example_blocks: list[dict],
    known_steps: set[str],
    flow_type: str,
    story_key: str,
    known_canonical: set[str] | None = None,
) -> tuple[str, list[dict]]:
    """
    Build a Scenario Outline block.
    Returns (block_text, unresolved_list).
    known_canonical: set of _canonicalize(s) for each corpus step — used for
    fuzzy grounding so pattern-matched steps are not falsely marked NEW.
    """
    unresolved: list[dict] = []
    lines: list[str] = []

    intent_text = intent.get("text", f"Intent {idx}")
    base_title  = intent_text if re.match(r"^[Vv]erify\s", intent_text) else f"Verify {intent_text}"

    # Step 13b/13c: title format from template
    if flow_type == "ordered":
        title = f"For App with [ <LogicalID> ] {base_title}"
    else:
        title = base_title

    lines.append(f"    Scenario Outline: {title}")

    # For ordered: inject prerequisite chain as first Given
    if flow_type == "ordered":
        lines.append(f"        Given {_PREREQ_STEP}")

    # Filter steps based on flow type
    steps_filtered: list[tuple[str, str]] = []
    for kw, step_text in raw_steps:
        # Unordered: strip login steps (they're in Background)
        if flow_type == "unordered" and step_text.lower().strip() in _LOGIN_STEPS_LOWER:
            continue
        # Ordered: strip any "all prerequisite are performed..." the LLM may have copied
        # from the source scenario — the assembler injects the canonical one above
        if flow_type == "ordered" and step_text.lower().startswith("all prerequisite are performed"):
            continue
        steps_filtered.append((kw, step_text))

    # Literalize: replace "quoted literals" with <ParamN> placeholders (scenario-scoped)
    steps_to_write, extra_param_cols = _literalize_steps(steps_filtered)

    # In ordered flow the prereq step was just added as Given above,
    # so all subsequent Given steps from LLM become And.
    # Also: if the first remaining step is And/But (login was stripped), promote to Given.
    seen_given_for_prereq = (flow_type == "ordered")
    first_step = True

    for kw, step_text in steps_to_write:
        actual_kw = kw
        if seen_given_for_prereq and kw == "Given":
            actual_kw = "And"
        elif first_step and actual_kw in ("And", "But"):
            actual_kw = "Given"
        first_step = False

        exact_match = step_text.lower().strip() in known_steps
        canonical_match = bool(known_canonical) and _canonicalize(step_text) in known_canonical
        is_grounded = exact_match or canonical_match
        marker = "" if is_grounded else "  # [NEW_STEP_NOT_IN_REPO]"
        lines.append(f"        {actual_kw} {step_text}{marker}")
        if not is_grounded:
            unresolved.append({"keyword": actual_kw, "step_text": step_text})

    # Step 13a: Examples table (extra_param_cols adds <ParamN> columns for literalized values)
    logical_id = f"{story_key.replace('-', '_')}_{idx:03d}"
    examples = _build_examples_table(
        steps_to_write, example_blocks, flow_type, logical_id, extra_cols=extra_param_cols
    )
    if examples:
        lines.append(examples)

    lines.append("")
    return "\n".join(lines), unresolved


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def forge_feature(
    story: JiraStory,
    intents: list[dict],
    flow_type: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> ForgeResult:
    """
    Phase A: for each intent, search → group scenarios → LLM picks + prunes.
    Saves intermediate JSON after Phase A.
    Phase B: assemble .feature file from intermediate scenarios using templates.
    LLM is always called — only skipped if retrieval returns nothing useful.
    """
    def _progress(msg: str):
        _log.info(msg)
        if on_progress:
            on_progress(msg)

    _progress(f"Starting forge for {len(intents)} intents...")

    # Extract the story's stage from system_process so retrieval can boost
    # same-stage scenarios even when an individual intent text omits the stage name.
    story_stage_hint: Optional[str] = detect_stage(
        (story.system_process or story.summary or "")[:500]
    )
    if story_stage_hint:
        _log.info("Story stage hint: %s", story_stage_hint)

    known_steps, known_canonical = _load_known_steps()
    scenarios_raw: list[dict] = []   # raw output from Phase A (before assembly)
    omitted: list[dict]       = []
    all_results: list[dict]   = []

    # ── Phase A: Retrieval + LLM ─────────────────────────────────────────────
    for i, intent in enumerate(intents, 1):
        intent_text = intent.get("text", "")
        _progress(f"[{i}/{len(intents)}] Retrieving: {intent_text[:60]}...")

        results = search(query=intent_text, top_k=20, stage_hint=story_stage_hint)
        all_results.extend(results)

        if not results:
            omitted.append({
                "intent_id": intent.get("id", f"intent_{i:03d}"),
                "intent":    intent_text,
                "reason":    "No matching steps found in repository",
            })
            continue

        top_score = max(r.get("score", 0.0) for r in results)
        if top_score < _MIN_RETRIEVAL_SCORE:
            omitted.append({
                "intent_id": intent.get("id", f"intent_{i:03d}"),
                "intent":    intent_text,
                "reason":    f"Retrieval scores too low (best: {top_score:.2f})",
            })
            continue

        unique_scenarios = _group_by_scenario(results)

        _progress(f"[{i}/{len(intents)}] LLM picking + pruning steps...")
        try:
            pruned_steps = _llm_pick_and_prune(intent, story, unique_scenarios)
        except Exception as e:
            _log.error("LLM call failed for intent '%s': %s", intent_text, e)
            omitted.append({
                "intent_id": intent.get("id", f"intent_{i:03d}"),
                "intent":    intent_text,
                "reason":    f"LLM error: {e}",
            })
            continue

        if not pruned_steps:
            omitted.append({
                "intent_id": intent.get("id", f"intent_{i:03d}"),
                "intent":    intent_text,
                "reason":    "LLM returned no step lines",
            })
            continue

        # If no Then step, synthesize a fallback assertion from the intent text
        # so the scenario is included rather than omitted (user can review/fix it)
        has_assertion = any(kw == "Then" for kw, _ in pruned_steps)
        if not has_assertion:
            synth = intent_text[0].lower() + intent_text[1:] if intent_text else "behavior is verified"
            pruned_steps.append(("Then", f"{synth}  # [SYNTHESIZED_ASSERTION - verify manually]"))
            _log.warning("No Then step from LLM for '%s' — synthesized fallback", intent_text)

        top_scen = unique_scenarios[0]
        scenarios_raw.append({
            "intent":                intent,
            "steps":                 pruned_steps,
            "example_blocks":        top_scen.get("example_blocks") or [],
            "source_scenario_title": top_scen.get("scenario_title", ""),
            "source_file":           top_scen.get("file_name", ""),
        })

    # Step 10: Save intermediate JSON before assembly
    scenarios_json_path = _save_scenarios_json(story, scenarios_raw, omitted)
    _progress(f"Scenarios saved: {scenarios_json_path}")

    # ── Phase B: Assembly ─────────────────────────────────────────────────────
    _progress("Assembling feature file...")
    product_types, app_stages = _collect_scope(all_results)
    header = _build_file_header(story, flow_type, product_types, app_stages)

    feature_parts  = [header]
    all_unresolved: list[dict] = []

    for idx, scen in enumerate(scenarios_raw, 1):
        scenario_text, unresolved = _build_scenario(
            scen["intent"], idx,
            scen["steps"],
            scen["example_blocks"],
            known_steps,
            flow_type,
            story.issue_key,
            known_canonical=known_canonical,
        )
        feature_parts.append(scenario_text)
        all_unresolved.extend(unresolved)

    feature_text = "\n".join(feature_parts).rstrip() + "\n"

    total_steps = sum(len(s["steps"]) for s in scenarios_raw)
    quality = {
        "scenario_count":   len(scenarios_raw),
        "total_steps":      total_steps,
        "grounded_steps":   total_steps - len(all_unresolved),
        "unresolved_steps": len(all_unresolved),
    }

    _progress(f"Done: {len(scenarios_raw)} scenarios, {len(omitted)} omitted")

    return ForgeResult(
        feature_text        = feature_text,
        quality             = quality,
        unresolved_steps    = all_unresolved,
        omitted_plan_items  = omitted,
        coverage_gaps       = [],
        scenario_debug      = [],
        scenarios_json_path = scenarios_json_path,
    )
