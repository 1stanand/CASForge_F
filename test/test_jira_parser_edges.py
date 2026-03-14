import unittest

from casforge.parsing.jira_parser import _clean, _split_process, load_all_stories, load_story
from casforge.shared.paths import SAMPLES_DIR, TEST_ROOT


class JiraParserEdgeTests(unittest.TestCase):
    def test_markup_cleanup(self):
        self.assertEqual(_clean("{-}strikethrough text{-}"), "strikethrough text")
        self.assertEqual(_clean("{color:#ff0000}red text{color}"), "red text")
        self.assertEqual(_clean("||Col1||Col2||Col3||"), "Col1 | Col2 | Col3")
        self.assertEqual(_clean("|cell1|cell2|cell3|"), "cell1 | cell2 | cell3")
        self.assertEqual(_clean("h1. Big Title"), "Big Title")
        self.assertEqual(_clean("*bold text*"), "bold text")
        self.assertEqual(_clean("+underline text+"), "underline text")
        self.assertEqual(_clean("*+bold underline+*"), "bold underline")
        self.assertEqual(_clean("[label|http://example.com]"), "label")
        self.assertEqual(_clean("{code:java}int x=1;{code}"), "")

    def test_split_process_headers(self):
        current, new = _split_process("Only new behaviour text")
        self.assertEqual(current, "")
        self.assertIn("Only new behaviour text", new)

        current, new = _split_process(
            "+*Current Process:-*+\nOld logic\n\n+*New Process:-*+\nNew logic"
        )
        self.assertIn("Old logic", current)
        self.assertIn("New logic", new)

    def test_sample_csv_loads(self):
        stories = load_all_stories(str(SAMPLES_DIR / "sampleJira" / "HD_BANK_EPIC.csv"))
        self.assertGreaterEqual(len(stories), 20)
        keys = {s.issue_key for s in stories}
        self.assertIn("CAS-256008", keys)

    def test_tiny_messy_csv_is_cleaned(self):
        story = load_story(str(TEST_ROOT / "resources" / "test-specs" / "tiny_messy.csv"), "TINY-2")
        merged = " ".join([
            story.description,
            story.new_process,
            story.business_scenarios,
            story.acceptance_criteria,
            story.story_description,
        ]).lower()
        self.assertNotIn("{color", merged)
        self.assertNotIn("{code", merged)
        self.assertNotIn("http://", merged)


if __name__ == "__main__":
    unittest.main()




