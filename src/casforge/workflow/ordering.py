"""
config/workflow.py
------------------
Parses order.json to build stage and sub-stage lookup maps used by retrieval.

order.json is the authoritative source for:
  - all stage annotation names (@Recommendation, @CreditApproval, ...)
  - all sub-stage modifier tags (@Guarantor, @Primary, @MoveToNext, ...)
  - the exact order in which CAS processes test scenarios

Exposes
-------
WORKFLOW_ORDER       list[str]   â€” ordered compound conditions from order.json
STAGE_TAGS           list[str]   â€” all primary stage tags (e.g. "@CreditApproval")
SUB_TAGS             list[str]   â€” modifier/sub-stage tags (e.g. "@Guarantor")
TEXT_TO_STAGE_TAG    dict        â€” query text â†’ canonical @StageName
TEXT_TO_SUB_TAG      dict        â€” query text â†’ canonical @SubName
"""

import json
import re
from typing import Optional

from casforge.shared.paths import ORDER_JSON_PATH

_ORDER_JSON = ORDER_JSON_PATH


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1. Load workflow order
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _load():
    with open(_ORDER_JSON, encoding="utf-8") as f:
        return json.load(f)["WorkFlow"]

WORKFLOW_ORDER: list[str] = _load()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 2. Extract tags
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# All unique @Tag names seen anywhere in the workflow
_ALL_TAGS: set[str] = set()
for _entry in WORKFLOW_ORDER:
    for _m in re.finditer(r'@\w+', _entry):
        _ALL_TAGS.add(_m.group(0))

# Primary stage tags = the leading @tag in each workflow entry
_STAGE_TAGS_SET: set[str] = set()
for _entry in WORKFLOW_ORDER:
    _m = re.match(r'(@\w+)', _entry.strip())
    if _m:
        _STAGE_TAGS_SET.add(_m.group(1))

# Sub-stage (modifier) tags = all other tags
_SUB_TAGS_SET: set[str] = _ALL_TAGS - _STAGE_TAGS_SET

STAGE_TAGS: list[str] = sorted(_STAGE_TAGS_SET)
SUB_TAGS:   list[str] = sorted(_SUB_TAGS_SET)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 3. Build text â†’ @Tag lookup maps
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _tag_to_phrases(tag: str) -> list[str]:
    """
    '@CreditApproval'  â†’  ['credit approval', 'creditapproval']
    '@KYC'             â†’  ['kyc']
    '@RcuInitiation'   â†’  ['rcu initiation', 'rcuinitiation', 'rcu']
    Longer phrases come first so they win in longest-match detection.
    """
    name = tag.lstrip('@')
    # Insert space before each capital that follows a lowercase (camelCase split)
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name).lower()
    words  = spaced.split()
    phrases = []
    phrases.append(spaced)                    # "credit approval"
    if len(words) > 1:
        phrases.append(''.join(words))        # "creditapproval"
        # Do NOT add single-word prefixes ("credit", "application", etc.)
        # â€” they cause false-positive stage detection on common words.
        # Use manual aliases in _STAGE_MANUAL / _SUB_MANUAL for short forms.
    return phrases


def _build_map(tag_set: set[str], manual: dict[str, str]) -> dict[str, str]:
    """
    Build text â†’ @Tag mapping.
    Longer text variants are added first; shorter ones only if key not yet present.
    Manual aliases always overwrite.
    """
    # Sort tags so longer generated phrases are processed first
    ordered = sorted(tag_set, key=lambda t: -len(t))
    result: dict[str, str] = {}
    for tag in ordered:
        for phrase in _tag_to_phrases(tag):
            if phrase not in result:
                result[phrase] = tag
    result.update(manual)   # manual aliases always win
    return result


# Manual aliases for abbreviations and common LLM phrasings
_STAGE_MANUAL: dict[str, str] = {
    "dde":                  "@DDE",
    "ccde":                 "@CCDE",
    "credit card dde":      "@CCDE",
    "kyc":                  "@KYC",
    "cii":                  "@CII",
    "civ":                  "@CIV",
    "cic":                  "@CIC",
    "fii":                  "@FII",
    "fiv":                  "@FIV",
    "fic":                  "@FIC",
    "icd":                  "@ICD",
    "fde":                  "@FDE",
    "rcu":                  "@RcuInitiation",
    "rcu initiation":       "@RcuInitiation",
    "rcu referral":         "@RcuReferral",
    "lms":                  "@LMS",
    "dcc":                  "@DCCScheduling",
    "ops":                  "@OperationCheck",
    "operations":           "@OperationCheck",
    "disbursal":            "@Disbursal",
    "disbursement":         "@Disbursal",
    "post approval":        "@PostApproval",
    "recommendation":       "@Recommendation",
    "login":                "@LoginAcceptance",
    "login acceptance":     "@LoginAcceptance",
    "pre sanction":         "@PreSanctionVisit",
    "pre-sanction":         "@PreSanctionVisit",
    "pre sanction visit":   "@PreSanctionVisit",
    "gold valuation":       "@GoldValuation",
    "asset validation":     "@AssetValidation",
    "credit bureau":        "@CreditBureauReferral",
    "reconsideration":      "@Reconsideration",
    "tranche initiation":   "@TrancheInitiation",
    "tranche approval":     "@TrancheApproval",
    "account updation":     "@AccountUpdation",
    "facility initiation":  "@FacilityInitiation",
    "credit approval":      "@CreditApproval",
    "bulk allocation":      "@BulkAllocationGrid",
    "cms":                  "@CMSModule",
    "lead details":         "@LeadDetails",
    "lead stage":           "@LeadDetails",
    "proposal":             "@Proposal",
    "enquiry":              "@Enquiry",
    "app update":           "@AppUpdateApproval",
    "app update approval":  "@AppUpdateApproval",
    "card management":      "@CardManagement",
    "sent to ops":          "@SentToOps",
    "dcc scheduling":       "@DCCScheduling",
    "dcc execution":        "@DCCExecution",
    "multiple disbursal":   "@MultipleDisbursal",
    "disbursal author":     "@DisbursalAuthor",
    "operation check":      "@OperationCheck",
}

_SUB_MANUAL: dict[str, str] = {
    "guarantor":            "@Guarantor",
    "co-applicant":         "@CoApplicant",
    "co applicant":         "@CoApplicant",
    "coapplicant":          "@CoApplicant",
    "primary applicant":    "@Primary",
    "primary":              "@Primary",
    "add on card":          "@AddOnCard",
    "add-on card":          "@AddOnCard",
    "addon card":           "@AddOnCard",
    "move to next":         "@MoveToNext",
    "move next":            "@MoveToNext",
    "next stage":           "@MoveToNext",
    "reject":               "@Reject",
    "rejection":            "@Reject",
    "open application":         "@OpenApplication",
    "pick application":         "@PickApplication",
    "collateral":               "@Collateral",
    "document approval":        "@DocumentApproval",
    "repayment instrument":     "@RepaymentInstrument",
    "periodic charge":          "@PeriodicCharge",
    "contractual charge":       "@ContractualCharge",
    "committee initiation":     "@CommitteeInitiation",
    "committee approval":       "@CommitteeApproval",
    "application manager":      "@ApplicationManager",
    "app info":                 "@AppInfo",
    "applicant info":           "@AppInfo",
    "loan details":             "@LoanDetails",
    "deal and facility":        "@DealAndFacilityDetails",
    "deal facility":            "@DealAndFacilityDetails",
    "group information":        "@GroupInformation",
    "move to next stage":       "@MoveToNext",
}

TEXT_TO_STAGE_TAG: dict[str, str] = _build_map(_STAGE_TAGS_SET, _STAGE_MANUAL)
TEXT_TO_SUB_TAG:   dict[str, str] = _build_map(_SUB_TAGS_SET,   _SUB_MANUAL)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 4. Pre-compiled detection patterns (longest phrase first)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _compile_patterns(text_map: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    """
    Build list of (regex_pattern, @Tag), sorted longest phrase first
    so more specific phrases match before shorter ones.
    """
    return sorted(
        [
            (re.compile(r'\b' + re.escape(phrase) + r'\b', re.IGNORECASE), tag)
            for phrase, tag in text_map.items()
        ],
        key=lambda x: -len(x[0].pattern)
    )

STAGE_PATTERNS: list[tuple[re.Pattern, str]] = _compile_patterns(TEXT_TO_STAGE_TAG)
SUB_PATTERNS:   list[tuple[re.Pattern, str]] = _compile_patterns(TEXT_TO_SUB_TAG)


def detect_stage(query: str) -> Optional[str]:
    """Return the canonical @StageName detected in query, or None."""
    for pattern, tag in STAGE_PATTERNS:
        if pattern.search(query):
            return tag
    return None


def detect_sub_tags(query: str) -> list[str]:
    """Return all canonical @SubTagNames detected in query (e.g. [@Guarantor, @Primary])."""
    found = []
    seen  = set()
    for pattern, tag in SUB_PATTERNS:
        if tag not in seen and pattern.search(query):
            found.append(tag)
            seen.add(tag)
    return found



