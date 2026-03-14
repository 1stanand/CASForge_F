"""
parser/screen_context.py
------------------------
Infers screen_context for every step in a scenario by detecting
"navigation anchor" steps and propagating the resolved canonical
screen name forward until the next anchor.

Navigation anchors are steps whose text contains verbs like:
  opens, navigates to, moves to, selects <ui-container>, clicks <ui-container>

The extracted phrase is normalised and looked up in SCREEN_NAME_MAP.
If found â†’ canonical name stored.
If not found â†’ screen_context remains None (clean null preferred over garbage).

Design notes
------------
- LogicalID prerequisite steps ("Given all prerequisite are performed...")
  are NOT treated as navigation anchors; they reference a prior scenario
  whose navigation we cannot see at parse time.
- "selects" is only treated as a navigation anchor when immediately
  followed by a UI-container word (tab, accordion, drawer, screen, page).
  "selects collateral type as" is a field interaction â€” ignored.
"""

import re
from typing import Optional

from casforge.shared.normalisation import SCREEN_NAME_MAP, _norm


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Anchor detection patterns
# Each pattern captures group(1) = the screen-name phrase.
# Patterns are applied to the *lowercased* step text.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ANCHOR_PATTERNS: list[re.Pattern] = [
    # "user opens the collateral screen"
    re.compile(
        r'\bopens?\s+(?:the\s+)?(.+?)(?:\s+(?:screen|page|tab|accordion|drawer))?\s*$',
        re.IGNORECASE
    ),
    # "user navigates to the KYC screen"
    re.compile(
        r'\bnavigates?\s+to\s+(?:the\s+)?(.+?)(?:\s+(?:screen|page|tab|accordion|drawer))?\s*$',
        re.IGNORECASE
    ),
    # "user moves to the next stage" â€” exclude "next stage" as a screen
    re.compile(
        r'\bmoves?\s+to\s+(?:the\s+)?(.+?)(?:\s+(?:screen|page|tab|accordion|drawer))?\s*$',
        re.IGNORECASE
    ),
    # "user selects the Documents tab"
    re.compile(
        r'\bselects?\s+(?:the\s+)?(.+?)\s+(?:tab|accordion|drawer|screen|page)\s*$',
        re.IGNORECASE
    ),
    # "user clicks on the Collateral tab"
    re.compile(
        r'\bclicks?\s+on\s+(?:the\s+)?(.+?)\s+(?:tab|accordion|drawer|screen|page)\s*$',
        re.IGNORECASE
    ),
    # "user is on the Recommendation screen"
    re.compile(
        r'\bis\s+on\s+(?:the\s+)?(.+?)(?:\s+(?:screen|page|tab|accordion|drawer))?\s*$',
        re.IGNORECASE
    ),
    # "Recommendation screen should be displayed"
    re.compile(
        r'^(.+?)\s+(?:screen|page)\s+should\s+be\s+(?:displayed|visible|opened|shown)',
        re.IGNORECASE
    ),
]

# Phrases that look like navigation anchors but are NOT screen names â€” skip them.
_IGNORE_PHRASES: frozenset[str] = frozenset({
    "next stage",
    "next",
    "previous stage",
    "back",
    "home",
    "dashboard",
})

# Step prefixes that indicate a LogicalID prerequisite â€” never parse for screen.
_LOGICAL_ID_PREFIX = "all prerequisite are performed"


def _extract_anchor_phrase(step_text: str) -> Optional[str]:
    """
    Return the raw screen-name phrase from a navigation anchor step,
    or None if the step is not a navigation anchor.
    """
    # Skip LogicalID prerequisite steps entirely
    lower = step_text.lower().strip()
    if _LOGICAL_ID_PREFIX in lower:
        return None

    for pattern in _ANCHOR_PATTERNS:
        m = pattern.search(lower)
        if m:
            phrase = m.group(1).strip()
            # Discard trivially short phrases and known non-screens
            if len(phrase) < 3:
                continue
            if _norm(phrase) in _IGNORE_PHRASES:
                continue
            return phrase

    return None


def resolve_screen(raw_phrase: str) -> Optional[str]:
    """
    Look up a raw phrase in SCREEN_NAME_MAP.
    Returns canonical screen name or None if not found.
    """
    key = _norm(raw_phrase)
    return SCREEN_NAME_MAP.get(key)


def infer_screen_contexts(steps: list[dict]) -> list[dict]:
    """
    Walk through an ordered list of step dicts and populate
    ``step['screen_context']`` on each step.

    Mutates the input list in-place AND returns it (for chaining).

    Each step dict must have at minimum:
        step_text : str

    After this call every step will also have:
        screen_context : str | None
    """
    current_screen: Optional[str] = None

    for step in steps:
        text = step.get("step_text", "")
        phrase = _extract_anchor_phrase(text)

        if phrase is not None:
            resolved = resolve_screen(phrase)
            # Only update current_screen when we can actually resolve the phrase.
            # If unresolvable, keep the previous screen â€” the tester navigated
            # somewhere we don't have in the map yet, but subsequent steps are
            # still logically "near" the last known screen.
            if resolved is not None:
                current_screen = resolved
            # If resolved is None, leave current_screen unchanged (caller's choice
            # to treat unresolved anchors as "unknown" can be toggled below).

        step["screen_context"] = current_screen

    return steps


def infer_screen_contexts_strict(steps: list[dict]) -> list[dict]:
    """
    Strict variant: if an anchor phrase cannot be resolved, set
    current_screen to None until the next resolvable anchor.
    Use this when you prefer clean nulls over stale values.
    """
    current_screen: Optional[str] = None

    for step in steps:
        text = step.get("step_text", "")
        phrase = _extract_anchor_phrase(text)

        if phrase is not None:
            current_screen = resolve_screen(phrase)  # may become None

        step["screen_context"] = current_screen

    return steps

