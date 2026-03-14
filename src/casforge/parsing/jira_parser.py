"""
jira/jira_parser.py
-------------------
Parse JIRA CSV exports and extract the fields CASForge needs for Phase 2.

JIRA CSVs from CAS projects have hundreds of columns.  This module reads only
the handful that matter for test-intent extraction and keeps everything else.

Usage
-----
    from casforge.parsing.jira_parser import load_story, load_all_stories

    story = load_story("workspace/samples/sampleJira/HD_BANK_EPIC.csv", "CAS-256008")
    print(story.summary)
    print(story.new_process)
"""

import csv
import re
from dataclasses import dataclass, field


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Data model
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class JiraStory:
    issue_key:           str
    summary:             str
    issue_type:          str
    description:         str          # raw user-story text ("As a user, I want...")
    current_process:     str          # what the system does today
    new_process:         str          # what the system should do after the change
    business_scenarios:  str          # exceptions / edge-cases from JIRA
    impacted_areas:      str          # CAS stages / modules affected
    key_ui_steps:        str          # navigation path, e.g. "CAS >> Applications >> CCDE"
    acceptance_criteria: str          # explicit AC if present
    story_description:   str          # "Story Description" custom field (sometimes richer)
    raw_labels:          list[str] = field(default_factory=list)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# JIRA column names we care about
# (CSV column headers vary slightly across exports â€” checked against HD Bank CSV)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_COL_SUMMARY          = "Summary"
_COL_KEY              = "Issue key"
_COL_TYPE             = "Issue Type"
_COL_DESCRIPTION      = "Description"
_COL_LABELS           = "Labels"
_COL_SYSTEM_PROCESS   = "Custom field (System processes)"
_COL_BIZ_SCENARIOS    = "Custom field (Business scenarios: Exceptions)"
_COL_BIZ_VALIDATION   = "Custom field (Business scenarios: Validations and corner cases)"
_COL_IMPACTED         = "Custom field (Impacted Areas/Functionalities)"
_COL_KEY_UI           = "Custom field (Key UI steps)"
_COL_ACCEPTANCE       = "Custom field (Acceptance Criteria)"
_COL_ACCEPTANCE_ALT   = "Custom field (Acceptance)"
_COL_STORY_DESC       = "Custom field (Story Description)"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Markup cleaning
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _clean(text: str) -> str:
    """Strip JIRA wiki markup and return plain text."""
    if not text:
        return ""
    # Normalise Windows line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Color macros:  {color:#hex}text{color}  â†’  text
    text = re.sub(r'\{color[^}]*\}', '', text)
    # Strikethrough:  {-}text{-}  â†’  text  (struck-through text still has context value)
    text = re.sub(r'\{-\}([^{]*)\{-\}', r'\1', text)
    # Superscript / subscript:  {^}text{^}  /  {~}text{~}
    text = re.sub(r'\{\^?\~?\}([^{]*)\{\^?\~?\}', r'\1', text)
    # Bold+underline combined (both orderings):  *+text+*  or  +*text*+
    text = re.sub(r'\*\+([^+]+)\+\*', r'\1', text)
    text = re.sub(r'\+\*+([^*]+)\*+\+', r'\1', text)
    # Bold:  *text*
    text = re.sub(r'\*([^*\n]+)\*', r'\1', text)
    # Underline:  +text+
    text = re.sub(r'\+([^+\n]+)\+', r'\1', text)
    # Italic:  _text_
    text = re.sub(r'_([^_\n]+)_', r'\1', text)
    # Wiki links / JIRA links:  [label|url]  or  [label]
    text = re.sub(r'\[([^\|\]]+)\|[^\]]+\]', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]', r'\1', text)
    # Table header rows:  ||Col1||Col2||  â†’  Col1 | Col2
    text = re.sub(r'^\|\|(.+?)\|\|$',
                  lambda m: ' | '.join(c.strip() for c in m.group(1).split('||')),
                  text, flags=re.MULTILINE)
    # Table data rows:  |cell1|cell2|  â†’  cell1 | cell2
    text = re.sub(r'^\|(.+?)\|$',
                  lambda m: ' | '.join(c.strip() for c in m.group(1).split('|') if c.strip()),
                  text, flags=re.MULTILINE)
    # JIRA emoticons:  (/)  (x)  (!)  (*)  (?)  â€” strip the parens notation
    text = re.sub(r'\([/\\xX!\*\?]\)', '', text)
    # Horizontal rule:  ----
    text = re.sub(r'^-{4,}$', '', text, flags=re.MULTILINE)
    # Code / noformat blocks:  {code:java}...{code}  â€” strip tag AND content
    # (code blocks contain implementation detail, not business behavior)
    text = re.sub(r'\{code[^}]*\}.*?\{code\}', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\{noformat[^}]*\}.*?\{noformat\}', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Quote / panel blocks:  {quote}...{quote}  {panel:...}...{panel}
    # Keep content (it's usually narrative), strip wrapper tags only
    text = re.sub(r'\{(?:quote|panel)[^}]*\}(.*?)\{(?:quote|panel)\}', r'\1',
                  text, flags=re.DOTALL)
    # Remaining single-line macro tags:  {anchor:...}, {toc}, etc.
    text = re.sub(r'\{[a-zA-Z][^}]*\}', '', text)
    # Heading markers:  h1. h2. etc.
    text = re.sub(r'^h[1-6]\.\s*', '', text, flags=re.MULTILINE)
    # Bullet markers (JIRA uses # and * at start of line)
    text = re.sub(r'^[#\*]+\s+', '- ', text, flags=re.MULTILINE)
    # Collapse excess whitespace / blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_process(raw: str) -> tuple[str, str]:
    """
    Split 'System processes' field into (current_process, new_process).

    The field typically looks like:
        +*Current Process:-*+
        There is no provision ...

        +*New Process:-*+
        Provision to be made ...
    """
    text = _clean(raw)
    lower = text.lower()
    new_idx = lower.find("new process")
    if new_idx == -1:
        # Whole thing is new process if it contains no "current" header either
        current_idx = lower.find("current process")
        if current_idx == -1:
            return "", text
        body = text[current_idx:]
        body = re.sub(r'^current process[:\-\s]+', '', body, flags=re.I).strip()
        return body, ""

    current_raw = text[:new_idx]
    new_raw     = text[new_idx:]

    current_raw = re.sub(r'^current process[:\-\s]+', '', current_raw, flags=re.I).strip()
    new_raw     = re.sub(r'^new process[:\-\s]+',     '', new_raw,     flags=re.I).strip()
    return current_raw, new_raw


def _get(row: dict, *keys: str) -> str:
    """Return the first non-empty value for any of the given column names."""
    for k in keys:
        v = row.get(k, "").strip()
        if v:
            return v
    return ""


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Public API
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_row(row: dict) -> JiraStory:
    current, new = _split_process(_get(row, _COL_SYSTEM_PROCESS))

    # Merge biz scenarios + validations into one block
    biz = "\n".join(filter(None, [
        _clean(_get(row, _COL_BIZ_SCENARIOS)),
        _clean(_get(row, _COL_BIZ_VALIDATION)),
    ])).strip()

    labels_raw = _get(row, _COL_LABELS)
    labels = [l.strip() for l in labels_raw.split(",") if l.strip()]

    return JiraStory(
        issue_key           = _get(row, _COL_KEY),
        summary             = _clean(_get(row, _COL_SUMMARY)),
        issue_type          = _get(row, _COL_TYPE),
        description         = _clean(_get(row, _COL_DESCRIPTION)),
        current_process     = current,
        new_process         = new,
        business_scenarios  = biz,
        impacted_areas      = _clean(_get(row, _COL_IMPACTED)),
        key_ui_steps        = _clean(_get(row, _COL_KEY_UI)),
        acceptance_criteria = _clean(_get(row, _COL_ACCEPTANCE, _COL_ACCEPTANCE_ALT)),
        story_description   = _clean(_get(row, _COL_STORY_DESC)),
        raw_labels          = labels,
    )


def load_story(csv_path: str, issue_key: str) -> JiraStory:
    """Load a single story by issue key from a JIRA CSV export."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get(_COL_KEY, "").strip() == issue_key:
                return _parse_row(row)
    raise ValueError(f"Story '{issue_key}' not found in {csv_path}")


def load_all_stories(csv_path: str, types: tuple[str, ...] = ("Story", "Bug", "Task")) -> list[JiraStory]:
    """Load all stories of the given issue types from a JIRA CSV export."""
    stories: list[JiraStory] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get(_COL_TYPE, "").strip() in types:
                stories.append(_parse_row(row))
    return stories


