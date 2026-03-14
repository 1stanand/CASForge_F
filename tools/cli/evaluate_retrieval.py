"""
scripts/evaluate_retrieval.py
-----------------------------
Runs retrieval accuracy checks on baseline, hard, regression, and negative queries.

Usage:
    python scripts/evaluate_retrieval.py
    python scripts/evaluate_retrieval.py --threshold 85
"""

from __future__ import annotations

import argparse
import os
import sys


from casforge.retrieval.retrieval import search


BASE_CASES = [
    ("guarantor details credit card", ["guarantor", "identification"]),
    ("guarantor section applicant information screen", ["guarantor", "applicant"]),
    ("remove guarantor applicant", ["remove", "guarantor"]),
    ("mandatory fields guarantor validation", ["mandatory", "guarantor"]),
    ("committee decision", ["committee"]),
    ("committee approval vote", ["committee"]),
    ("credit approval stage move to next", ["credit", "move to"]),
    ("recommendation screen", ["recommendation"]),
    ("cancel confirm days LOB level", ["cancel"]),
    ("add on applicant dynamic form placeholder CCDE", ["dynamic form", "add on"]),
    ("KYC screen display guarantor details", ["kyc", "guarantor"]),
    ("document collection release print", ["document"]),
    ("deviation policy facility wise", ["deviation"]),
    ("screen display button", ["button", "visible"]),
    ("user clicks on Move to Next Stage button", ["move to next stage"]),
]

HARD_CASES = [
    ("guarantor at creditapproval stage", ["guarantor"], "@CreditApproval"),
    ("guarantor at dde stage", ["guarantor"], "@DDE"),
    ("committee approval credit approval", ["committee"], "@CreditApproval"),
    ("applicant information screen guarantor", ["guarantor"], None),
    ("guarant section applic info", ["guarantor"], None),
    ("commit decis voting", ["committee"], None),
    ("guarentor detailes creditcard", ["guarantor"], None),
    ("guarantor", ["guarantor"], None),
    ("guarantor at kyc stage", ["guarantor"], "@KYC"),
    ("move to next stage button", ["move to next"], None),
    ("xyzzy frobnicator nonexistent term", [], None),
]


def _top_blob(results: list[dict]) -> str:
    if not results:
        return ""
    top = results[0]
    return f"{top.get('step_text', '')} {top.get('scenario_title', '')}".lower()


def _run_base() -> tuple[int, int]:
    passed = 0
    for query, hints in BASE_CASES:
        results = search(query, top_k=5)
        top = _top_blob(results)
        ok = bool(results) and any(h in top for h in hints)
        print(
            f"[{'OK' if ok else 'FAIL'}] {query:<52} "
            f"top={results[0]['keyword'] + ': ' + results[0]['step_text'][:58] if results else 'NONE'}"
        )
        passed += int(ok)
    return passed, len(BASE_CASES)


def _run_hard() -> tuple[int, int]:
    passed = 0
    for query, hints, expected_stage in HARD_CASES:
        results = search(query, top_k=5)
        detected_stage = results[0].get("detected_stage") if results else None
        top = _top_blob(results)
        hint_ok = (not hints) or any(h in top for h in hints)
        stage_ok = expected_stage is None or detected_stage == expected_stage
        ok = bool(results) and hint_ok and stage_ok
        print(
            f"[{'OK' if ok else 'FAIL'}] {query:<52} "
            f"stage={detected_stage or '(none)':<16} "
            f"top={results[0]['keyword'] + ': ' + results[0]['step_text'][:46] if results else 'NONE'}"
        )
        passed += int(ok)
    return passed, len(HARD_CASES)


def _run_keyword_filters() -> bool:
    print("\nKeyword filter checks:")
    all_ok = True
    for kw in ("Given", "When", "Then", "And", "But"):
        results = search("guarantor", top_k=5, keyword_filter=kw)
        ok = all(r.get("keyword") == kw for r in results)
        all_ok = all_ok and ok
        print(f"  {'[OK]' if ok else '[FAIL]'} {kw:<5} n={len(results)}")
    return all_ok


def _run_negative() -> bool:
    print("\nNegative intent sanity:")
    query = "completely unrelated quantum spaceship mortgage banana"
    results = search(query, top_k=5)
    non_increasing = all(
        results[i]["score"] <= results[i - 1]["score"] for i in range(1, len(results))
    )
    ok = len(results) <= 5 and all(r["score"] >= 0 for r in results) and non_increasing
    print(
        f"  {'[OK]' if ok else '[FAIL]'} n={len(results)} "
        f"top_scores={[round(r['score'], 4) for r in results[:3]]}"
    )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Minimum overall accuracy percentage required to pass (default: 80)",
    )
    args = parser.parse_args()

    print("=== Baseline retrieval ===")
    base_pass, base_total = _run_base()
    base_pct = (base_pass / base_total) * 100
    print(f"Baseline: {base_pass}/{base_total} = {base_pct:.1f}%\n")

    print("=== Hard retrieval ===")
    hard_pass, hard_total = _run_hard()
    hard_pct = (hard_pass / hard_total) * 100
    print(f"Hard: {hard_pass}/{hard_total} = {hard_pct:.1f}%\n")

    overall_pass = base_pass + hard_pass
    overall_total = base_total + hard_total
    overall_pct = (overall_pass / overall_total) * 100

    kw_ok = _run_keyword_filters()
    neg_ok = _run_negative()

    print("\n=== Summary ===")
    print(f"Overall retrieval: {overall_pass}/{overall_total} = {overall_pct:.1f}%")
    print(f"Keyword filters: {'PASS' if kw_ok else 'FAIL'}")
    print(f"Negative sanity: {'PASS' if neg_ok else 'FAIL'}")
    print(f"Threshold ({args.threshold:.1f}%): {'PASS' if overall_pct >= args.threshold else 'FAIL'}")

    return 0 if overall_pct >= args.threshold and kw_ok and neg_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


