"""
parser/feature_parser.py
------------------------
Bulletproof Gherkin parser for the CAS ATDD repository.

Handles every known CAS extension on top of standard Gherkin:
  â€¢ Comment-driven dictionary expansion  #${Key=["v1","v2"]}
  â€¢ Annotation tags                       @Order  @AuthoredBy: name
  â€¢ @Order / @E2EOrder file-level flags
  â€¢ LogicalID prerequisite steps
  â€¢ Background: sections
  â€¢ Doc strings  \"\"\"...\"\"\"
  â€¢ Mixed CRLF/LF line endings
  â€¢ Non-UTF-8 files (replaced with U+FFFD)
  â€¢ BOM at file start

Public API
----------
parse_file(file_path: str) -> ParsedFeature
    Parse a single .feature file.  Never raises â€” errors are captured
    inside ParsedFeature.parse_error.

ParsedFeature  â€” dataclass-like dict with keys:
    file_path, file_name, feature_title,
    file_annotations, file_dicts,
    is_order_file, is_e2e_order, has_conflict, parse_error,
    scenarios: list[ParsedScenario]

ParsedScenario â€” dict with keys:
    title, is_outline, scenario_annotations, scenario_dicts,
    scenario_index, steps: list[ParsedStep],
    example_blocks: list[ParsedExampleBlock]

ParsedStep â€” dict with keys:
    keyword, step_text, step_position, screen_context

ParsedExampleBlock â€” dict with keys:
    block_annotations, block_dicts, headers, rows, block_index
"""

import os
import re
import json
import logging
from typing import Optional

from casforge.shared.normalisation import STEP_KEYWORD_MAP, _norm
from casforge.parsing.screen_context import infer_screen_contexts

logger = logging.getLogger(__name__)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Regex constants
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Matches:  #${Key=["v1","v2"]}  or  ##${Key=['v1','v2']}  or  #### ${Key=[...]}
# Also handles: ${Key=["v1"]}  without comment prefix (rare but seen)
_DICT_RE = re.compile(
    r'\$\{(\w+)\s*=\s*\[(.*?)\]\}',
    re.IGNORECASE | re.DOTALL
)

# Annotation line: starts with @ (possibly after whitespace)
# Captures the full annotation string including any colon-suffix
_ANNOTATION_RE = re.compile(r'^\s*@(.+)')

# Gherkin keyword at start of line (after optional whitespace)
_KEYWORD_RE = re.compile(
    r'^\s*(Feature|Background|Scenario Outline|Scenario|Examples?|Given|When|Then|And|But|\*)\s*:?\s*(.*)',
    re.IGNORECASE
)

# Table row detection
_TABLE_ROW_RE = re.compile(r'^\s*\|')

# Doc string delimiter
_DOC_STRING_RE = re.compile(r'^\s*("""|\'\'\')(.*)')

# LogicalID prerequisite step marker (never parse for navigation)
_LOGICAL_ID_MARKER = "all prerequisite are performed"

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Type aliases (plain dicts, not dataclasses, for easy JSON serialisation)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

ParsedStep          = dict   # keyword, step_text, step_position, screen_context
ParsedExampleBlock  = dict   # block_annotations, block_dicts, headers, rows, block_index
ParsedScenario      = dict   # title, is_outline, ..., steps, example_blocks
ParsedFeature       = dict   # file_path, ..., scenarios


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Low-level helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _read_lines(file_path: str) -> list[str]:
    """
    Read a file handling:
      - BOM (UTF-8 BOM at start)
      - Non-UTF-8 bytes (replaced with U+FFFD)
      - CRLF â†’ LF normalisation
    Returns list of raw lines (newlines stripped).
    """
    with open(file_path, encoding="utf-8-sig", errors="replace") as fh:
        content = fh.read()
    # Normalise line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content.split("\n")


def _strip_line(line: str) -> str:
    """Strip trailing whitespace. Keep indentation intentionally."""
    return line.rstrip()


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _is_comment(line: str) -> bool:
    """True for pure comment lines (start with # but not a dict definition)."""
    stripped = line.strip()
    return stripped.startswith("#") and not _DICT_RE.search(stripped)


def _is_dict_line(line: str) -> bool:
    return bool(_DICT_RE.search(line))


def _is_annotation_line(line: str) -> bool:
    return bool(_ANNOTATION_RE.match(line))


def _parse_annotations(lines: list[str]) -> list[str]:
    """
    Extract all @annotation strings from a list of lines.
    Handles:
      @Tag
      @Tag: value
      @Tag:value  (no space)
    Returns list of normalised strings like "@Order", "@AuthoredBy: anand.singh1"
    """
    result = []
    for line in lines:
        m = _ANNOTATION_RE.match(line)
        if m:
            tag = m.group(1).strip()
            if tag:
                result.append("@" + tag)
    return result


def _parse_dicts(lines: list[str]) -> dict:
    """
    Extract all #${Key=["v1","v2"]} definitions from a list of lines.
    Handles both double-quoted and single-quoted values.
    Returns {key: [values]}.
    If a key appears multiple times, later definitions override earlier ones.
    """
    result = {}
    for line in lines:
        for m in _DICT_RE.finditer(line):
            key = m.group(1).strip()
            raw_values = m.group(2)
            # Split on comma, strip quotes and whitespace
            values = []
            for token in raw_values.split(","):
                v = token.strip().strip('"').strip("'").strip()
                if v:
                    values.append(v)
            result[key] = values
    return result


def _check_conflict(file_annotations: list[str], file_dicts: dict) -> bool:
    """
    True if the file has both @Order/@E2EOrder AND dictionary definitions â€”
    a combination the CAS framework does not support.
    """
    has_order = any(
        ann.lower() in ("@order", "@e2eorder")
        for ann in file_annotations
    )
    return has_order and bool(file_dicts)


def _normalise_keyword(raw: str) -> str:
    """Given raw keyword string â†’ canonical keyword."""
    return STEP_KEYWORD_MAP.get(raw.strip().lower(), raw.strip().capitalize())


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Table parser
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_table_row(line: str) -> list[str]:
    """
    Parse a Gherkin table row like: | foo | bar | baz |
    Returns list of cell strings (stripped).
    """
    # Strip leading/trailing | and whitespace, then split on |
    inner = line.strip().strip("|")
    return [cell.strip() for cell in inner.split("|")]


def _parse_table(lines: list[str]) -> tuple[list[str], list[dict]]:
    """
    Parse a Gherkin table (Examples block body).
    First row = headers.
    Subsequent rows = data rows as {header: value} dicts.
    Returns (headers, rows).
    """
    table_lines = [l for l in lines if _TABLE_ROW_RE.match(l)]
    if not table_lines:
        return [], []

    headers = _parse_table_row(table_lines[0])
    rows = []
    for row_line in table_lines[1:]:
        cells = _parse_table_row(row_line)
        # Pad or trim to match header count
        while len(cells) < len(headers):
            cells.append("")
        row_dict = {headers[i]: cells[i] for i in range(len(headers))}
        rows.append(row_dict)

    return headers, rows


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Line classifier â€” used in the main state machine
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _LT:
    """Line type constants."""
    BLANK       = "blank"
    COMMENT     = "comment"
    DICT        = "dict"
    ANNOTATION  = "annotation"
    FEATURE     = "feature"
    BACKGROUND  = "background"
    SCENARIO    = "scenario"
    OUTLINE     = "outline"
    EXAMPLES    = "examples"
    STEP        = "step"
    TABLE_ROW   = "table_row"
    DOC_STRING  = "doc_string"
    OTHER       = "other"


def _classify(line: str) -> tuple[str, str, str]:
    """
    Classify a single line.
    Returns (line_type, keyword_or_empty, remainder_text).
    """
    stripped = line.strip()

    if not stripped:
        return _LT.BLANK, "", ""

    if _is_dict_line(line):
        return _LT.DICT, "", stripped

    if stripped.startswith("#"):
        return _LT.COMMENT, "", stripped

    if stripped.startswith("@"):
        return _LT.ANNOTATION, "", stripped

    if _TABLE_ROW_RE.match(line):
        return _LT.TABLE_ROW, "", stripped

    doc_m = _DOC_STRING_RE.match(line)
    if doc_m:
        return _LT.DOC_STRING, doc_m.group(1), doc_m.group(2).strip()

    kw_m = _KEYWORD_RE.match(line)
    if kw_m:
        raw_kw  = kw_m.group(1).strip()
        rest    = kw_m.group(2).strip()
        kw_lower = raw_kw.lower()

        if kw_lower == "feature":
            return _LT.FEATURE, raw_kw, rest
        if kw_lower == "background":
            return _LT.BACKGROUND, raw_kw, rest
        if kw_lower == "scenario outline":
            return _LT.OUTLINE, raw_kw, rest
        if kw_lower == "scenario":
            return _LT.SCENARIO, raw_kw, rest
        if kw_lower in ("examples", "example"):
            return _LT.EXAMPLES, raw_kw, rest
        if kw_lower in ("given", "when", "then", "and", "but", "*"):
            return _LT.STEP, raw_kw, rest

    return _LT.OTHER, "", stripped


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Main parser
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def parse_file(file_path: str) -> ParsedFeature:
    """
    Parse a single .feature file.

    Returns a ParsedFeature dict. Never raises â€” all exceptions are
    captured into the ``parse_error`` field.
    """
    file_name = os.path.basename(file_path)

    result: ParsedFeature = {
        "file_path":         file_path,
        "file_name":         file_name,
        "feature_title":     None,
        "file_annotations":  [],
        "file_dicts":        {},
        "is_order_file":     False,
        "is_e2e_order":      False,
        "has_conflict":      False,
        "parse_error":       None,
        "scenarios":         [],
    }

    try:
        lines = _read_lines(file_path)
    except Exception as exc:
        result["parse_error"] = f"read error: {exc}"
        return result

    if not any(l.strip() for l in lines):
        result["parse_error"] = "empty file"
        return result

    try:
        _parse_lines(lines, result)
    except Exception as exc:
        logger.exception("Unexpected parse error in %s", file_path)
        result["parse_error"] = f"parse error: {exc}"

    return result


def _parse_lines(lines: list[str], result: ParsedFeature) -> None:
    """
    Core line-by-line state machine.
    Mutates ``result`` in place.
    """
    # â”€â”€ State variables â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    STATE_FILE_HEADER   = "FILE_HEADER"
    STATE_IN_SCENARIO   = "IN_SCENARIO"
    STATE_IN_EXAMPLES   = "IN_EXAMPLES"
    STATE_IN_DOCSTRING  = "IN_DOCSTRING"

    state = STATE_FILE_HEADER

    # Accumulated pending lines before Feature: / Scenario / Examples
    pending_annotations: list[str] = []
    pending_dict_lines:  list[str] = []
    pending_other:       list[str] = []

    # Current objects being built
    current_scenario: Optional[ParsedScenario]      = None
    current_example:  Optional[ParsedExampleBlock]  = None
    current_step:     Optional[ParsedStep]          = None

    # Doc-string tracking
    doc_string_delimiter = None
    doc_string_lines: list[str] = []

    # Background steps (injected into all scenarios)
    background_steps: list[ParsedStep] = []
    in_background = False

    scenario_index = 0

    def flush_pending_to(target: str) -> tuple[list[str], dict]:
        """Return (annotations, dicts) from pending buffers and clear them."""
        nonlocal pending_annotations, pending_dict_lines, pending_other
        anns  = _parse_annotations(pending_annotations)
        dicts = _parse_dicts(pending_dict_lines)
        pending_annotations = []
        pending_dict_lines  = []
        pending_other       = []
        return anns, dicts

    def close_current_step():
        """Append current_step to current_scenario if open."""
        nonlocal current_step
        if current_step is not None and current_scenario is not None:
            current_scenario["steps"].append(current_step)
            current_step = None

    def close_current_example():
        """Append current_example to current_scenario if open."""
        nonlocal current_example
        if current_example is not None and current_scenario is not None:
            current_scenario["example_blocks"].append(current_example)
            current_example = None

    def close_current_scenario():
        """Finalise and append current_scenario to result."""
        nonlocal current_scenario, in_background
        if current_scenario is None:
            return
        close_current_step()
        close_current_example()
        # Apply screen context inference
        infer_screen_contexts(current_scenario["steps"])
        if in_background:
            # Accumulate background steps; don't add as a real scenario
            nonlocal background_steps
            background_steps = list(current_scenario["steps"])
            in_background = False
        else:
            # Prepend background steps (if any) â€” shallow copy with reset positions
            if background_steps:
                bg = []
                for i, s in enumerate(background_steps):
                    bg.append({
                        "keyword":        s["keyword"],
                        "step_text":      s["step_text"],
                        "step_position":  i,
                        "screen_context": s.get("screen_context"),
                    })
                # Re-position existing steps
                offset = len(bg)
                for s in current_scenario["steps"]:
                    s["step_position"] += offset
                current_scenario["steps"] = bg + current_scenario["steps"]
                # Re-infer screen context on combined steps
                infer_screen_contexts(current_scenario["steps"])
            result["scenarios"].append(current_scenario)
        current_scenario = None

    def open_scenario(title: str, is_outline: bool, scenario_anns: list[str], scenario_dicts: dict):
        nonlocal current_scenario, scenario_index
        close_current_scenario()
        current_scenario = {
            "title":                 title,
            "is_outline":            is_outline,
            "scenario_annotations":  scenario_anns,
            "scenario_dicts":        scenario_dicts,
            "scenario_index":        scenario_index,
            "steps":                 [],
            "example_blocks":        [],
        }
        scenario_index += 1

    def open_example_block(block_anns: list[str], block_dicts: dict, block_index: int):
        nonlocal current_example
        close_current_example()
        current_example = {
            "block_annotations": block_anns,
            "block_dicts":       block_dicts,
            "headers":           [],
            "rows":              [],
            "block_index":       block_index,
            "_header_set":       False,  # internal flag
        }

    # â”€â”€ Main loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    feature_seen = False

    for raw_line in lines:
        line = _strip_line(raw_line)
        lt, kw, rest = _classify(line)

        # â”€â”€ Doc-string mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if state == STATE_IN_DOCSTRING:
            if lt == _LT.DOC_STRING and kw == doc_string_delimiter:
                # Closing delimiter â€” append accumulated doc string to current step
                if current_step is not None:
                    current_step["step_text"] += "\n" + "\n".join(doc_string_lines)
                doc_string_lines = []
                doc_string_delimiter = None
                state = STATE_IN_SCENARIO
            else:
                doc_string_lines.append(line)
            continue

        # â”€â”€ Opening a doc string â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if lt == _LT.DOC_STRING:
            doc_string_delimiter = kw
            doc_string_lines = []
            state = STATE_IN_DOCSTRING
            continue

        # â”€â”€ File header (before Feature:) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if state == STATE_FILE_HEADER:
            if lt == _LT.FEATURE:
                if not feature_seen:
                    feature_seen = True
                    result["feature_title"] = rest if rest else None
                    anns, dicts = flush_pending_to("feature")
                    result["file_annotations"] = anns
                    result["file_dicts"]        = dicts
                    # Set order flags
                    lower_anns = [a.lower() for a in anns]
                    result["is_order_file"] = "@order" in lower_anns
                    result["is_e2e_order"]  = "@e2eorder" in lower_anns
                    result["has_conflict"]  = _check_conflict(anns, dicts)
                    if result["has_conflict"]:
                        logger.warning(
                            "%s: has both @Order and dictionary definitions (invalid combo)",
                            result["file_path"]
                        )
                    state = STATE_IN_SCENARIO  # Scenarios start here
                else:
                    logger.warning("%s: duplicate Feature: line ignored", result["file_path"])
                continue

            if lt == _LT.ANNOTATION:
                pending_annotations.append(line)
            elif lt == _LT.DICT:
                pending_dict_lines.append(line)
            elif lt not in (_LT.BLANK, _LT.COMMENT):
                pending_other.append(line)
            continue

        # â”€â”€ In scenario body â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if state in (STATE_IN_SCENARIO, STATE_IN_EXAMPLES):

            if lt == _LT.BACKGROUND:
                close_current_scenario()
                in_background = True
                open_scenario("__background__", False, [], {})
                state = STATE_IN_SCENARIO
                continue

            if lt in (_LT.SCENARIO, _LT.OUTLINE):
                anns, dicts = flush_pending_to("scenario")
                is_outline = (lt == _LT.OUTLINE)
                open_scenario(rest, is_outline, anns, dicts)
                state = STATE_IN_SCENARIO
                continue

            if lt == _LT.EXAMPLES:
                if current_scenario is None:
                    logger.warning(
                        "%s: Examples block outside any scenario â€” skipping",
                        result["file_path"]
                    )
                    continue
                if not current_scenario["is_outline"]:
                    logger.warning(
                        "%s: Examples block in non-outline scenario '%s'",
                        result["file_path"], current_scenario["title"]
                    )
                close_current_step()
                anns, dicts = flush_pending_to("examples")
                block_index = len(current_scenario["example_blocks"])
                if current_example is not None:
                    close_current_example()
                open_example_block(anns, dicts, block_index)
                state = STATE_IN_EXAMPLES
                continue

            if lt == _LT.STEP:
                if current_scenario is None:
                    # Step outside any scenario â€” silently skip
                    continue
                # Close previous step before opening new one
                close_current_step()
                # If currently in examples state and we see a step,
                # it means a new Scenario Outline started (unusual but handle it)
                if state == STATE_IN_EXAMPLES:
                    # Treat as continuation â€” rare; just record
                    pass
                pos = len(current_scenario["steps"])
                canonical_kw = _normalise_keyword(kw)
                current_step = {
                    "keyword":        canonical_kw,
                    "step_text":      rest,
                    "step_position":  pos,
                    "screen_context": None,
                }
                continue

            if lt == _LT.TABLE_ROW:
                # Either part of an Examples table or a data table inside a step
                if state == STATE_IN_EXAMPLES and current_example is not None:
                    if not current_example["_header_set"]:
                        current_example["headers"] = _parse_table_row(line)
                        current_example["_header_set"] = True
                    else:
                        cells = _parse_table_row(line)
                        headers = current_example["headers"]
                        while len(cells) < len(headers):
                            cells.append("")
                        row_dict = {headers[i]: cells[i] for i in range(len(headers))}
                        current_example["rows"].append(row_dict)
                elif current_step is not None:
                    # Data table attached to the step â€” append raw
                    current_step["step_text"] += "\n" + line.strip()
                continue

            if lt == _LT.ANNOTATION:
                pending_annotations.append(line)
                continue

            if lt == _LT.DICT:
                pending_dict_lines.append(line)
                continue

            if lt in (_LT.BLANK, _LT.COMMENT, _LT.OTHER):
                # Blank / comment lines between scenarios or inside a step's body
                # If there's a pending step, close it (blank line ends step)
                if lt == _LT.BLANK and current_step is not None:
                    close_current_step()
                continue

            if lt == _LT.FEATURE:
                if not feature_seen:
                    logger.warning("%s: Feature: found inside scenario block â€” ignoring", result["file_path"])
                continue

    # â”€â”€ End of file â€” close whatever is open â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    close_current_scenario()

    # Clean up internal flags from example_blocks
    for sc in result["scenarios"]:
        for eb in sc["example_blocks"]:
            eb.pop("_header_set", None)

