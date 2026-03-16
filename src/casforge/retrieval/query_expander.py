"""
catalogue/query_expander.py
---------------------------
Query expansion pre-processor for the retrieval pipeline.

Short queries like "Delete Guarantor" or "visible at Recommendation" suffer
because the action verb in the query ("delete", "visible") doesn't literally
match the verb in the step corpus ("removes", "present", "see").

This module:
  1. Detects action-verb synonyms in the query.
  2. Produces two expanded forms:
       - word-form  (appended to query string) → used by vector + trigram channels
       - OR-form    (formatted for websearch_to_tsquery) → used by FTS channel

Only queries with ≤ 6 words are expanded — longer queries have enough context.
"""

import re

# Common noisy spellings/abbreviations seen in real JIRA/LLM intent text.
# These are conservative replacements to avoid over-normalising good queries.
_TERM_NORMALISATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bguarentor\b", re.I), "guarantor"),
    (re.compile(r"\bgurantor\b", re.I), "guarantor"),
    (re.compile(r"\bguarantar\b", re.I), "guarantor"),
    (re.compile(r"\bdetailes\b", re.I), "details"),
    (re.compile(r"\bcreditcard\b", re.I), "credit card"),
    (re.compile(r"\bcommitee\b", re.I), "committee"),
    (re.compile(r"\bcommit\b", re.I), "committee"),
    (re.compile(r"\bdecis\b", re.I), "decision"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Synonym groups
# Each entry: (trigger_pattern, [list of canonical synonyms to inject])
# The trigger must match in the query to activate expansion for that group.
# All synonyms are added to the expanded query (deduped against existing words).
# ─────────────────────────────────────────────────────────────────────────────

_SYNONYM_GROUPS: list[tuple[re.Pattern, list[str]]] = [
    # ── Deletion / removal ──────────────────────────────────────────────────
    (re.compile(r'\b(delete|deletes|deleted|remove|removes|removed|clear|erase)\b', re.I),
     ['delete', 'remove', 'removes', 'deleted']),

    # ── Visibility / presence ───────────────────────────────────────────────
    (re.compile(r'\b(visible|visibility|show|shown|display|displayed|present|see|view|available|appear)\b', re.I),
     ['visible', 'show', 'display', 'present', 'see', 'available']),

    # ── Rejection ───────────────────────────────────────────────────────────
    (re.compile(r'\b(reject|rejected|rejection|decline|declined|disapprove|not approve)\b', re.I),
     ['reject', 'rejected', 'rejection', 'decline']),

    # ── Addition / creation ─────────────────────────────────────────────────
    (re.compile(r'\b(add|added|adds|create|created|insert|attach|include)\b', re.I),
     ['add', 'added', 'adds', 'create', 'insert']),

    # ── Submission / saving ─────────────────────────────────────────────────
    (re.compile(r'\b(submit|submits|save|saves|confirm|complete|finish|proceed)\b', re.I),
     ['submit', 'save', 'confirm', 'complete', 'proceed']),

    # ── Approval ────────────────────────────────────────────────────────────
    (re.compile(r'\b(approve|approves|approved|sanction|sanctioned|accept|accepted)\b', re.I),
     ['approve', 'approved', 'sanction', 'accept']),

    # ── Editing / updating ──────────────────────────────────────────────────
    (re.compile(r'\b(edit|edits|update|updates|modify|modifies|change|alter)\b', re.I),
     ['edit', 'update', 'modify', 'change']),

    # ── Navigation / opening ────────────────────────────────────────────────
    (re.compile(r'\b(open|opens|opened|launch|navigate|access|go to)\b', re.I),
     ['open', 'opens', 'opened', 'navigate', 'access']),

    # ── Verification / checking ─────────────────────────────────────────────
    (re.compile(r'\b(verify|validates|validate|check|checks|assert|assertion)\b', re.I),
     ['verify', 'validate', 'check', 'confirm']),

    # ── Selection / picking ─────────────────────────────────────────────────
    (re.compile(r'\b(pick|picks|select|selects|choose|search|find)\b', re.I),
     ['pick', 'select', 'choose', 'search', 'find']),

    # ── Initiation ──────────────────────────────────────────────────────────
    (re.compile(r'\b(initiate|initiates|initiated|start|starts|begin|trigger)\b', re.I),
     ['initiate', 'initiated', 'start', 'begin']),

    # ── Pending / waiting ───────────────────────────────────────────────────
    (re.compile(r'\b(pending|wait|waiting|hold|on hold|not yet)\b', re.I),
     ['pending', 'wait', 'hold']),

    # ── Checkbox / toggle state ──────────────────────────────────────────────
    # Covers intent phrases like "default all checkboxes to checked" or
    # "decision checkbox unchecked by default" that otherwise miss CAS corpus matches.
    (re.compile(r'\b(checked|unchecked|checkbox|check box|ticked|unticked|toggled)\b', re.I),
     ['checked', 'unchecked', 'checkbox', 'selected']),

    # ── Disabled / read-only field state ────────────────────────────────────
    (re.compile(r'\b(disabled|readonly|read only|non.editable|grayed|greyed)\b', re.I),
     ['disabled', 'readonly', 'read only', 'non-editable']),

    # ── Default state ────────────────────────────────────────────────────────
    (re.compile(r'\bdefault\b', re.I),
     ['default', 'by default', 'initial', 'pre-selected']),
]

# Maximum number of synonym words appended per group (keeps queries tight)
_MAX_EXTRA_PER_GROUP = 3

# Only expand queries shorter than this word count.
# Intent texts from the LLM are typically 8–12 words; capping at 3 prevented
# most real queries from getting any expansion. Raised to 10 so medium-length
# intents like "Default all decision checkboxes to checked at Recommendation"
# still get synonym enrichment.
_MAX_WORDS_TO_EXPAND = 10


def normalise_query_text(query: str) -> str:
    """
    Normalise known misspellings/abbreviations before retrieval channels run.

    This improves hard real-world prompts like:
      - "guarentor detailes creditcard"
      - "commit decis voting"
    """
    if not query:
        return query
    out = query
    for pattern, replacement in _TERM_NORMALISATIONS:
        out = pattern.sub(replacement, out)
    return out


def _collect_extras(query: str) -> list[str]:
    """Return synonym words not already present in the query."""
    q_lower = query.lower()
    extra: list[str] = []
    seen: set[str] = set()

    for pattern, synonyms in _SYNONYM_GROUPS:
        if not pattern.search(query):
            continue
        count = 0
        for syn in synonyms:
            if syn not in seen and syn.lower() not in q_lower:
                extra.append(syn)
                seen.add(syn)
                count += 1
                if count >= _MAX_EXTRA_PER_GROUP:
                    break

    return extra


def expand_for_vector(query: str) -> str:
    """
    Append synonym words to the query for the vector embedding channel.
    Only applied to short queries where a few extra words noticeably
    shift the embedding toward the intended action.

    Example:
        "Delete Guarantor"  →  "Delete Guarantor remove removes deleted"
        "visible at Recommendation stage"
            →  "visible at Recommendation stage show display present see available"
    """
    if not query or len(query.split()) > _MAX_WORDS_TO_EXPAND:
        return query

    extras = _collect_extras(query)
    if not extras:
        return query

    return query + ' ' + ' '.join(extras)


def expand_for_fts(query: str) -> str:
    """
    Format the query for use with websearch_to_tsquery.
    Synonym alternatives are expressed as OR clauses so FTS uses
    (delete OR remove) & guarantor semantics, not AND.

    Example:
        "Delete Guarantor"
            →  '(delete OR remove OR removes OR deleted) Guarantor'
    """
    if not query or len(query.split()) > _MAX_WORDS_TO_EXPAND:
        return query

    q_lower = query.lower()
    # Collect per-group OR expansions
    or_groups: list[str] = []
    matched_words: set[str] = set()

    for pattern, synonyms in _SYNONYM_GROUPS:
        m = pattern.search(query)
        if not m:
            continue
        trigger_word = m.group(0).lower()
        matched_words.add(trigger_word)

        # Build OR list of synonyms that aren't already in query
        or_list = [trigger_word]
        for syn in synonyms:
            if syn.lower() != trigger_word and syn.lower() not in q_lower:
                or_list.append(syn)

        if len(or_list) > 1:
            or_groups.append('(' + ' OR '.join(or_list) + ')')

    if not or_groups:
        return query

    # Remove matched trigger words from the base query so they don't
    # appear twice (once plain, once inside the OR group)
    base = query
    for word in matched_words:
        base = re.sub(r'\b' + re.escape(word) + r'\b', '', base, flags=re.I)
    base = ' '.join(base.split())  # normalise whitespace

    parts = or_groups
    if base.strip():
        parts.append(base.strip())

    return ' '.join(parts)


def expand_for_trigram(query: str) -> str:
    """
    Same as expand_for_vector — appends synonym words.
    Trigram word_similarity benefits from more overlapping substrings.
    """
    return expand_for_vector(query)
