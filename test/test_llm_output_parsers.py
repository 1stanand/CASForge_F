import unittest

from casforge.parsing.jira_parser import JiraStory
from casforge.generation.feature_assembler import _clean_output, _enforce_cas_format
from casforge.generation.intent_extractor import _parse_intents


class LlmOutputParserTests(unittest.TestCase):
    def _story(self):
        return JiraStory(
            issue_key="CAS-TEST",
            summary="Sample Story",
            issue_type="Story",
            description="desc",
            current_process="",
            new_process="new",
            business_scenarios="",
            impacted_areas="",
            key_ui_steps="",
            acceptance_criteria="",
            story_description="",
            raw_labels=[],
        )

    def test_parse_intents_json_and_fenced_json(self):
        raw = '["A", "B"]'
        self.assertEqual(_parse_intents(raw), ["A", "B"])

        fenced = "```json\n[\"A\", \"B\"]\n```"
        self.assertEqual(_parse_intents(fenced), ["A", "B"])

    def test_parse_intents_tolerates_trailing_comma_and_preamble(self):
        raw = 'Model output:\n["A", "B",]\nThanks'
        self.assertEqual(_parse_intents(raw), ["A", "B"])

    def test_parse_intents_empty(self):
        self.assertEqual(_parse_intents(""), [])
        self.assertEqual(_parse_intents("   "), [])

    def test_clean_output_strips_preamble_and_trailing_noise(self):
        raw = (
            "Here is your file:\n\n"
            "Feature: Demo\n\n"
            "  Scenario Outline: S1\n"
            "    Given step one\n"
            "    When step two\n"
            "    Then step three\n\n"
            "    @DDE\n"
            "    Examples:\n"
            "      | x |\n"
            "      | y |\n\n"
            "Extra explanation that should be removed."
        )
        cleaned = _clean_output(raw, self._story())
        self.assertTrue(cleaned.startswith("Feature: Demo"))
        self.assertNotIn("Extra explanation", cleaned)

    def test_clean_output_prepends_feature_if_missing(self):
        raw = "Scenario Outline: S1\nGiven step\nWhen step\nThen step"
        cleaned = _clean_output(raw, self._story())
        self.assertTrue(cleaned.startswith("Feature: Sample Story"))

    def test_enforce_cas_format(self):
        raw = (
            "Feature: Demo @CreditApproval @Guarantor\n\n"
            "  Scenario: S1\n"
            "    Given g\n"
            "    When w\n"
            "    Then t\n"
        )
        fixed = _enforce_cas_format(raw, "@CreditApproval", ["@Guarantor"])
        self.assertIn("Feature: Demo", fixed)
        self.assertNotIn("Feature: Demo @CreditApproval", fixed)
        self.assertIn("Scenario Outline: S1", fixed)
        self.assertIn("@CreditApproval @Guarantor", fixed)
        self.assertIn("Examples:", fixed)


if __name__ == "__main__":
    unittest.main()

