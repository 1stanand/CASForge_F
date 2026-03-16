import unittest

from casforge.parsing.jira_parser import JiraStory
from casforge.generation.intent_extractor import _parse_intents


class LlmOutputParserTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
