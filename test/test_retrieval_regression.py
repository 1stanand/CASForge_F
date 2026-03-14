import unittest

from casforge.retrieval.query_expander import normalise_query_text
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


class RetrievalRegressionTests(unittest.TestCase):
    def _top_blob(self, results):
        if not results:
            return ""
        top = results[0]
        return f"{top.get('step_text', '')} {top.get('scenario_title', '')}".lower()

    def test_query_normalisation(self):
        self.assertEqual(
            normalise_query_text("guarentor detailes creditcard"),
            "guarantor details credit card",
        )
        self.assertEqual(
            normalise_query_text("commit decis voting"),
            "committee decision voting",
        )

    def test_base_queries(self):
        passed = 0
        for query, hints in BASE_CASES:
            results = search(query, top_k=5)
            self.assertTrue(results, f"No results for query: {query}")
            top_blob = self._top_blob(results)
            if any(h in top_blob for h in hints):
                passed += 1

        accuracy = passed / len(BASE_CASES)
        self.assertGreaterEqual(
            accuracy,
            0.90,
            f"Base retrieval accuracy below 90%: {passed}/{len(BASE_CASES)}",
        )

    def test_hard_queries(self):
        passed = 0
        for query, hints, expected_stage in HARD_CASES:
            results = search(query, top_k=5)
            self.assertTrue(results, f"No results for hard query: {query}")
            top = results[0]
            top_blob = self._top_blob(results)
            hint_ok = (not hints) or any(h in top_blob for h in hints)
            stage_ok = expected_stage is None or top.get("detected_stage") == expected_stage
            if hint_ok and stage_ok:
                passed += 1

        accuracy = passed / len(HARD_CASES)
        self.assertGreaterEqual(
            accuracy,
            0.80,
            f"Hard retrieval accuracy below 80%: {passed}/{len(HARD_CASES)}",
        )

    def test_keyword_filter_strict(self):
        for kw in ("Given", "When", "Then", "And", "But"):
            results = search("guarantor", top_k=5, keyword_filter=kw)
            self.assertTrue(
                all(r.get("keyword") == kw for r in results),
                f"Keyword filter leaked non-{kw} rows",
            )

    def test_negative_query_sanity(self):
        results = search("completely unrelated quantum spaceship mortgage banana", top_k=5)
        self.assertLessEqual(len(results), 5)
        for i, row in enumerate(results):
            self.assertGreaterEqual(row.get("score", 0.0), 0.0, f"negative score at index {i}")
            if i > 0:
                self.assertLessEqual(row["score"], results[i - 1]["score"])


if __name__ == "__main__":
    unittest.main()

