import unittest

from guide_comparison.diff.text_diff import inline_diff, normalize_text


class TextDiffTests(unittest.TestCase):
    def test_normalization_preserves_meaningful_characters(self):
        self.assertEqual(normalize_text("  A\r\n  30일!  "), "A 30일!")

    def test_inline_change_detects_numbers(self):
        old, new = inline_diff("평가 기간은 30일입니다.", "평가 기간은 40일입니다.")
        self.assertEqual("".join(c.text for c in old if c.changed), "30")
        self.assertEqual("".join(c.text for c in new if c.changed), "40")


if __name__ == "__main__":
    unittest.main()

