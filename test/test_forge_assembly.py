"""
test_forge_assembly.py
----------------------
Unit tests for forge.py assembly functions.
No LLM or database required — all functions accept plain dicts/lists.
"""

import unittest
from casforge.generation.forge import (
    _parse_gwt_lines,
    _group_by_scenario,
    _build_examples_table,
    _build_scenario,
)
from casforge.parsing.jira_parser import JiraStory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _story(key="CAS-001", summary="Test Story"):
    return JiraStory(
        issue_key=key, summary=summary,
        description="", system_process="Recommendation",
        acceptance_criteria="", business_scenarios="",
        impacted_areas="", key_ui_steps="", story_description="",
    )


def _intent(text="Verify something", family="positive", idx=1):
    return {"id": f"intent_{idx:03d}", "text": text, "family": family}


# ---------------------------------------------------------------------------
# _parse_gwt_lines
# ---------------------------------------------------------------------------

class TestParseGwtLines(unittest.TestCase):

    def test_basic_gwt(self):
        raw = "Given user opens screen\nWhen user clicks save\nThen success message shown"
        result = _parse_gwt_lines(raw)
        self.assertEqual(result, [
            ("Given", "user opens screen"),
            ("When", "user clicks save"),
            ("Then", "success message shown"),
        ])

    def test_and_keyword(self):
        raw = "Given user opens screen\nAnd user is logged in\nThen page loads"
        result = _parse_gwt_lines(raw)
        self.assertEqual(result[1], ("And", "user is logged in"))

    def test_strips_bullet_prefix(self):
        raw = "- Given user opens screen\n* Then result appears"
        result = _parse_gwt_lines(raw)
        self.assertEqual(result[0][0], "Given")
        self.assertEqual(result[1][0], "Then")

    def test_ignores_blank_lines(self):
        raw = "Given step one\n\n\nThen step two"
        result = _parse_gwt_lines(raw)
        self.assertEqual(len(result), 2)

    def test_empty_input(self):
        self.assertEqual(_parse_gwt_lines(""), [])
        self.assertEqual(_parse_gwt_lines("   "), [])

    def test_skips_keyword_with_no_text(self):
        # "Given " with nothing after should be skipped
        raw = "Given \nWhen user acts\nThen result"
        result = _parse_gwt_lines(raw)
        # "Given " alone should be dropped
        self.assertNotIn(("Given", ""), result)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# _group_by_scenario
# ---------------------------------------------------------------------------

class TestGroupByScenario(unittest.TestCase):

    def _make_result(self, title, file, score, steps=None):
        return {
            "scenario_title": title,
            "file_name": file,
            "score": score,
            "scenario_steps": steps or [{"keyword": "Given", "step_text": "user does something"}],
            "example_blocks": [],
        }

    def test_groups_by_title_and_file(self):
        results = [
            self._make_result("Scenario A", "file1.feature", 0.9),
            self._make_result("Scenario A", "file1.feature", 0.7),  # duplicate
            self._make_result("Scenario B", "file2.feature", 0.8),
        ]
        groups = _group_by_scenario(results)
        self.assertEqual(len(groups), 2)

    def test_keeps_max_score_for_duplicates(self):
        results = [
            self._make_result("Scenario A", "file1.feature", 0.5),
            self._make_result("Scenario A", "file1.feature", 0.9),
        ]
        groups = _group_by_scenario(results)
        self.assertEqual(groups[0]["_score"], 0.9)

    def test_returns_at_most_5(self):
        results = [self._make_result(f"Scenario {i}", "file.feature", 0.5 - i * 0.01)
                   for i in range(10)]
        groups = _group_by_scenario(results)
        self.assertLessEqual(len(groups), 5)

    def test_sorted_by_score_descending(self):
        results = [
            self._make_result("Low",  "a.feature", 0.3),
            self._make_result("High", "b.feature", 0.9),
            self._make_result("Mid",  "c.feature", 0.6),
        ]
        groups = _group_by_scenario(results)
        self.assertEqual(groups[0]["scenario_title"], "High")
        self.assertEqual(groups[-1]["scenario_title"], "Low")

    def test_empty_input(self):
        self.assertEqual(_group_by_scenario([]), [])


# ---------------------------------------------------------------------------
# _build_examples_table
# ---------------------------------------------------------------------------

class TestBuildExamplesTable(unittest.TestCase):

    def test_unordered_uses_step_variables(self):
        steps = [("Given", 'user opens "<ProductType>" application')]
        table = _build_examples_table(steps, [], "unordered", "CAS_001_001")
        self.assertIsNotNone(table)
        self.assertIn("ProductType", table)
        self.assertIn("Examples:", table)

    def test_ordered_always_has_logicalid(self):
        steps = [("Given", "user opens application")]
        table = _build_examples_table(steps, [], "ordered", "CAS_001_001")
        self.assertIsNotNone(table)
        self.assertIn("LogicalID", table)
        self.assertIn("CAS_001_001", table)

    def test_no_variables_and_no_eb_returns_producttype_column(self):
        # Unordered with no <Variable> in steps — should default to ProductType column
        steps = [("Given", "user opens screen")]
        table = _build_examples_table(steps, [], "unordered", "X_001")
        self.assertIsNotNone(table)

    def test_uses_real_example_block_data(self):
        steps = [("Given", 'application of "<ProductType>"')]
        example_blocks = [{"headers": ["ProductType"], "rows": [{"ProductType": "HL"}]}]
        table = _build_examples_table(steps, example_blocks, "unordered", "X_001")
        self.assertIn("HL", table)

    def test_multiple_variables(self):
        steps = [("When", 'user sets "<ProductType>" at "<ApplicationStage>"')]
        table = _build_examples_table(steps, [], "unordered", "X_001")
        self.assertIn("ProductType", table)
        self.assertIn("ApplicationStage", table)


# ---------------------------------------------------------------------------
# _build_scenario (integration of step writing + grounding)
# ---------------------------------------------------------------------------

class TestBuildScenario(unittest.TestCase):

    def test_ungrounded_step_gets_marker(self):
        intent = _intent("Verify decision checkbox visible")
        steps = [
            ("Given", "user is on CAS Login Page"),
            ("When", "user navigates to recommendation screen"),
            ("Then", "decision checkbox should be visible_UNIQUE_NONEXISTENT_XYZ"),
        ]
        known = {"user is on cas login page", "user navigates to recommendation screen"}
        text, unresolved = _build_scenario(intent, 1, steps, [], known, "unordered", "CAS-001")
        self.assertIn("[NEW_STEP_NOT_IN_REPO]", text)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("decision checkbox", unresolved[0]["step_text"])

    def test_grounded_step_has_no_marker(self):
        intent = _intent("Verify login")
        steps = [("Given", "user is on cas login page")]
        known = {"user is on cas login page"}
        text, unresolved = _build_scenario(intent, 1, steps, [], known, "unordered", "CAS-001")
        self.assertNotIn("[NEW_STEP_NOT_IN_REPO]", text)
        self.assertEqual(unresolved, [])

    def test_ordered_injects_prereq_step(self):
        intent = _intent("Verify flow")
        steps = [("When", "user clicks save"), ("Then", "success shown")]
        known = set()
        text, _ = _build_scenario(intent, 1, steps, [], known, "ordered", "CAS-001")
        self.assertIn("all prerequisite are performed in previous scenario", text)

    def test_leading_and_promoted_to_given_unordered(self):
        # If LLM returns "And" as first step (login was stripped), promote to Given
        intent = _intent("Verify something")
        steps = [
            ("And", "user is on recommendation page"),  # should be promoted to Given
            ("When", "user clicks submit"),
            ("Then", "result visible"),
        ]
        known = set()
        text, _ = _build_scenario(intent, 1, steps, [], known, "unordered", "CAS-001")
        # The "And" step should appear as "Given" since it's first and unordered
        self.assertIn("        Given user is on recommendation page", text)

    def test_login_steps_stripped_in_unordered(self):
        intent = _intent("Verify decision")
        steps = [
            ("Given", "user is on CAS Login Page"),
            ("When", "user navigates to screen"),
            ("Then", "decision visible"),
        ]
        known = set()
        text, _ = _build_scenario(intent, 1, steps, [], known, "unordered", "CAS-001")
        # Login step should NOT appear since Background handles it in unordered flow
        self.assertNotIn("user is on CAS Login Page", text)

    def test_scenario_outline_title_added(self):
        intent = _intent("Verify decision checkbox visible")
        steps = [("Given", "setup"), ("When", "action"), ("Then", "result")]
        known = set()
        text, _ = _build_scenario(intent, 1, steps, [], known, "unordered", "CAS-001")
        self.assertIn("Scenario Outline:", text)
        self.assertIn("Verify decision checkbox visible", text)


if __name__ == "__main__":
    unittest.main()
