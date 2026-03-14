"""
config/normalisation.py
-----------------------
Canonical lookup maps used throughout CASForge.

SCREEN_NAME_MAP   : alias → canonical screen name
                    Derived from CAS_SCREEN_OVERVIEW.md.
                    Keys are lowercase, whitespace-collapsed, articles stripped.

LOB_MAP           : raw token → canonical LOB code
                    Handles case variations and full-name forms.

STAGE_MAP         : raw token → canonical stage name
                    Used when inferring stage context from annotations or text.

STEP_KEYWORD_MAP  : normalise "given/when/then/and/but" to canonical keyword.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Helper used at import time to build normalised keys
# ─────────────────────────────────────────────────────────────────────────────
import re as _re


def _norm(text: str) -> str:
    """Lowercase, strip articles, collapse whitespace."""
    t = text.lower()
    t = _re.sub(r'\b(the|a|an)\b', '', t)
    return _re.sub(r'\s+', ' ', t).strip()


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN_NAME_MAP
# Keys   : normalised alias strings (output of _norm())
# Values : canonical screen name (stored in screen_context column)
# ─────────────────────────────────────────────────────────────────────────────

_RAW_SCREEN_MAP: dict[str, str] = {

    # ── Lead Details / General ─────────────────────────────────────────────
    "applicant information":        "Applicant Information",
    "applicant info":               "Applicant Information",
    "applicant details":            "Applicant Information",
    "applicant piano":              "Applicant Information",
    "applicant profile":            "Applicant Information",
    "add applicant":                "Applicant Information",
    "add co-applicant":             "Applicant Information",
    "add coapplicant":              "Applicant Information",

    "personal information":         "Personal Information",
    "personal info":                "Personal Information",
    "personal details":             "Personal Information",

    "employment details":           "Employment Details",
    "employment":                   "Employment Details",
    "occupation details":           "Employment Details",

    "financial details":            "Financial Details",
    "financial":                    "Financial Details",
    "income details":               "Financial Details",

    "bank details":                 "Bank Details",
    "bank":                         "Bank Details",
    "bank account details":         "Bank Details",

    "re-kyc":                       "Re-KYC",
    "rekyc":                        "Re-KYC",
    "re kyc":                       "Re-KYC",

    "need analysis":                "Need Analysis",
    "need analysis section":        "Need Analysis",

    "loan information":             "Loan Information",
    "loan details":                 "Loan Information",
    "loan info":                    "Loan Information",

    "sourcing details":             "Sourcing Details",
    "sourcing information":         "Sourcing Details",
    "sourcing info":                "Sourcing Details",
    "sourcing":                     "Sourcing Details",

    "property details":             "Property Details",
    "property":                     "Property Details",
    "property and registration details": "Property Details",
    "property registration details": "Property Details",

    "lien details":                 "Lien Details",
    "lien":                         "Lien Details",

    "cersai details":               "Cersai Details",
    "cersai":                       "Cersai Details",

    "asset details":                "Asset Details",
    "asset detail":                 "Asset Details",

    "asset requested":              "Asset Requested",

    "repayment parameters":         "Repayment Parameters",
    "loan parameters":              "Repayment Parameters",
    "loan parameter":               "Repayment Parameters",
    "repayment":                    "Repayment Parameters",

    "receipts":                     "Receipts",
    "receipt":                      "Receipts",
    "receipts section":             "Receipts",

    "documents":                    "Documents",
    "document":                     "Documents",
    "document tab":                 "Documents",
    "documents tab":                "Documents",

    "personal discussion":          "Personal Discussion",

    "balance transfer":             "Balance Transfer",
    "bt details":                   "Balance Transfer",
    "bt":                           "Balance Transfer",

    "card details":                 "Card Details",
    "card detail":                  "Card Details",

    "collateral":                   "Collateral",
    "collateral tab":               "Collateral",
    "collateral screen":            "Collateral",
    "collateral page":              "Collateral",

    "collateral details":           "Collateral Details",
    "collateral detail":            "Collateral Details",

    # ── Login Acceptance ───────────────────────────────────────────────────
    "login acceptance":             "Login Acceptance",
    "login":                        "Login Acceptance",

    # ── KYC ───────────────────────────────────────────────────────────────
    "kyc":                          "KYC",
    "kyc details":                  "KYC",
    "know your customer":           "KYC",
    "kyc screen":                   "KYC",

    # ── DDE ───────────────────────────────────────────────────────────────
    "deviations":                   "Deviations",
    "deviation":                    "Deviations",
    "deviation section":            "Deviations",
    "business deviations":          "Deviations",
    "credit deviations":            "Deviations",
    "manual deviation":             "Deviations",
    "raise deviation":              "Deviations",

    # ── Recommendation ────────────────────────────────────────────────────
    "recommendation":               "Recommendation",
    "recommendations":              "Recommendation",

    # ── Credit Approval ───────────────────────────────────────────────────
    "underwriter decision":         "Underwriter Decision",
    "credit approval":              "Underwriter Decision",
    "underwriter decisions":        "Underwriter Decision",

    "credit decisioning":           "Credit Decisioning",
    "credit decision":              "Credit Decisioning",

    "decision details":             "Decision Details",
    "decisions":                    "Decision Details",
    "decision":                     "Decision Details",

    "product type decisions":       "Product Type Decisions",
    "product type":                 "Product Type Decisions",

    "card type decisions":          "Card Type Decisions",
    "card type":                    "Card Type Decisions",

    "approval checklist":           "Approval Checklist",

    "committee":                    "Committee",
    "committee approval":           "Committee",
    "committee decision":           "Committee",

    "cam report":                   "CAM Report",
    "cam":                          "CAM Report",

    "score card":                   "Score Card",
    "scorecard":                    "Score Card",

    # ── Reconsideration ───────────────────────────────────────────────────
    "reconsideration":              "Reconsideration",

    # ── Post Approval ─────────────────────────────────────────────────────
    "post approval":                "Post Approval",
    "pdoc":                         "Post Approval",
    "post approval documents":      "Post Approval",

    "repayment instruments":        "Repayment Instruments",
    "repayment instrument":         "Repayment Instruments",
    "repayment instrument details": "Repayment Instruments",

    # ── Disbursal ─────────────────────────────────────────────────────────
    "disbursal":                    "Disbursal",
    "disbursal details":            "Disbursal",
    "disbursement details":         "Disbursal",
    "disbursal entry":              "Disbursal",
    "disbursal main":               "Disbursal",
    "disbursal maker":              "Disbursal",
    "disbursal author":             "Disbursal",

    # ── Parallel stages: Collateral Investigation ─────────────────────────
    "collateral investigation initiation":  "Collateral Investigation Initiation",
    "collateral investigation":             "Collateral Investigation Initiation",
    "cii":                                  "Collateral Investigation Initiation",

    "collateral investigation verification": "Collateral Investigation Verification",
    "civ":                                   "Collateral Investigation Verification",

    "collateral investigation completion":   "Collateral Investigation Completion",
    "cic":                                   "Collateral Investigation Completion",

    # ── Parallel stages: Field Investigation ─────────────────────────────
    "field investigation initiation":   "Field Investigation Initiation",
    "field investigation":              "Field Investigation Initiation",
    "fii":                              "Field Investigation Initiation",

    "field investigation verification": "Field Investigation Verification",
    "fiv":                              "Field Investigation Verification",

    "field investigation completion":   "Field Investigation Completion",
    "fic":                              "Field Investigation Completion",

    # ── Parallel stages: RCU ──────────────────────────────────────────────
    "rcu initiation":       "RCU Initiation",
    "rcu init":             "RCU Initiation",
    "rcu":                  "RCU Initiation",

    "rcu verification":     "RCU Verification",
    "rcu verify":           "RCU Verification",

    "rcu completion":       "RCU Completion",
    "rcu complete":         "RCU Completion",

    "rcu referral":         "RCU Referral",

    # ── LOB-specific screens ──────────────────────────────────────────────
    "investor details":             "Investor Details",

    "bond allocation":              "Bond Allocation",

    "metal allocation":             "Metal Allocation",

    "share holding details":        "Share Holding Details",
    "share holding":                "Share Holding Details",

    "corporate rating":             "Corporate Rating",

    "partners & directors":         "Partners & Directors",
    "partners and directors":       "Partners & Directors",
    "partners directors":           "Partners & Directors",

    "shg details":                  "SHG Details",

    "gold valuation":               "Gold Valuation",

    "land holding summary":         "Land Holding Summary",
    "land holding":                 "Land Holding Summary",

    "crop details":                 "Crop Details",

    "cattle details":               "Cattle Details",

    "subsidy details":              "Subsidy Details",
    "subsidy":                      "Subsidy Details",

    "vap details":                  "VAP Details",
    "vap detail":                   "VAP Details",

    "waiver initiation":            "Waiver Initiation",
    "waiver":                       "Waiver Initiation",

    "waiver verification":          "Waiver Verification",

    "waiver approval":              "Waiver Approval",
}

# Build the final map with normalised keys
SCREEN_NAME_MAP: dict[str, str] = {_norm(k): v for k, v in _RAW_SCREEN_MAP.items()}


# ─────────────────────────────────────────────────────────────────────────────
# LOB_MAP
# Maps raw LOB strings (case-insensitive) → canonical short codes
# ─────────────────────────────────────────────────────────────────────────────
LOB_MAP: dict[str, str] = {
    # Mortgage
    "hl":               "HL",
    "home loan":        "HL",
    "lap":              "LAP",
    "loan against property": "LAP",
    "mhf":              "MHF",
    "micro housing finance": "MHF",
    "micro housing":    "MHF",

    # Movable Asset
    "auto":             "Auto",
    "auto loan":        "Auto",
    "cv":               "CV",
    "commercial vehicle": "CV",
    "commercial vehicle loan": "CV",
    "ceq":              "CEQ",
    "commercial equipment": "CEQ",
    "commercial equipment loan": "CEQ",
    "tl":               "TL",
    "tractor loan":     "TL",
    "farm equipment loan": "TL",

    # Other
    "omni":             "Omni",
    "omni loan":        "Omni",
    "agri":             "Agri",
    "agriculture loan": "Agri",
    "pl":               "PL",
    "personal loan":    "PL",
    "cc":               "CC",
    "credit card":      "CC",
    "credit card loan": "CC",
    "el":               "EL",
    "education loan":   "EL",
    "fas":              "FAS",
    "finance against security": "FAS",
    "finance against securities": "FAS",
    "cd":               "CD",
    "consumer durable": "CD",
    "consumer durable loan": "CD",
    "proposal":         "CD",
    "shg":              "SHG",
    "self help group":  "SHG",
    "jlg":              "JLG",
    "joint liability group": "JLG",
    "corp":             "Corp",
    "corporate":        "Corp",
    "multi facility":   "Corp",
    "gl":               "GL",
    "gold loan":        "GL",
}

# Build normalised version
LOB_MAP = {_norm(k): v for k, v in LOB_MAP.items()}


# ─────────────────────────────────────────────────────────────────────────────
# STAGE_MAP
# Maps annotation tags and text variants → canonical stage names
# ─────────────────────────────────────────────────────────────────────────────
STAGE_MAP: dict[str, str] = {
    # Annotations (as they appear in feature files)
    "@lead":                "Lead Details",
    "@leaddetails":         "Lead Details",
    "@lead details":        "Lead Details",
    "@loginacceptance":     "Login Acceptance",
    "@login":               "Login Acceptance",
    "@kyc":                 "KYC",
    "@dde":                 "DDE",
    "@ccde":                "DDE",          # Credit Card DDE variant
    "@fde":                 "DDE",          # some files use FDE
    "@recommendation":      "Recommendation",
    "@rec":                 "Recommendation",
    "@creditapproval":      "Credit Approval",
    "@credit":              "Credit Approval",
    "@reconsideration":     "Reconsideration",
    "@postapproval":        "Post Approval",
    "@pdoc":                "Post Approval",
    "@disbursal":           "Disbursal",
    "@disbursalinitiation": "Disbursal Initiation",
    "@disbursalauthor":     "Disbursal",
    # App Update sub-flow
    "@appupdate":           "App Update",
    "@appupdaterecommendation": "App Update Recommendation",
    "@appupdateapproval":   "App Update Approval",
    "@aua":                 "App Update Approval",
    # Parallel stages
    "@cii":                 "Collateral Investigation Initiation",
    "@civ":                 "Collateral Investigation Verification",
    "@cic":                 "Collateral Investigation Completion",
    "@fii":                 "Field Investigation Initiation",
    "@fiv":                 "Field Investigation Verification",
    "@fic":                 "Field Investigation Completion",
    "@rcu":                 "RCU Initiation",
    "@rcuinit":             "RCU Initiation",
    "@rcuverify":           "RCU Verification",
    "@rcucomplete":         "RCU Completion",
    # Text forms (lowercase, no @)
    "lead details":         "Lead Details",
    "lead":                 "Lead Details",
    "login acceptance":     "Login Acceptance",
    "login":                "Login Acceptance",
    "kyc":                  "KYC",
    "dde":                  "DDE",
    "recommendation":       "Recommendation",
    "credit approval":      "Credit Approval",
    "reconsideration":      "Reconsideration",
    "post approval":        "Post Approval",
    "disbursal":            "Disbursal",
}

# Build normalised version
STAGE_MAP = {_norm(k): v for k, v in STAGE_MAP.items()}


# ─────────────────────────────────────────────────────────────────────────────
# STEP_KEYWORD_MAP
# Normalises the Gherkin keyword to a canonical 5-value set.
# ─────────────────────────────────────────────────────────────────────────────
STEP_KEYWORD_MAP: dict[str, str] = {
    "given": "Given",
    "when":  "When",
    "then":  "Then",
    "and":   "And",
    "but":   "But",
    "*":     "And",   # Gherkin also allows bare *
}
