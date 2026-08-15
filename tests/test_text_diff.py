import unittest

from guide_comparison.diff.models import TextBlock
from guide_comparison.diff.text_diff import inline_diff, inline_diff_blocks, matching_text, normalize_text, similarity


class TextDiffTests(unittest.TestCase):
    @staticmethod
    def block_with_chars(text):
        chars = []
        x = 0.0
        for char in text:
            chars.append((char, x, 0.0, x + 1.0, 1.0))
            x += 1.0
        return TextBlock(text, chars=chars)

    def test_normalization_preserves_meaningful_characters(self):
        self.assertEqual(normalize_text("  A\r\n  30일!  "), "A 30일!")

    def test_matching_ignores_layout_spacing_and_unicode_variants(self):
        self.assertEqual(matching_text("사전 GMP 평가 – 지침"), matching_text("사전GMP평가-지침"))
        self.assertEqual(similarity("사전 GMP 평가 – 지침", "사전GMP평가-지침"), 1.0)

    def test_block_diff_ignores_moved_line_breaks_and_keeps_changed_rects(self):
        old = self.block_with_chars("작성되었으므 로 2025년 9월 알려드 립니다.")
        new = self.block_with_chars("작성되었으 므로 2026년 8월 알려드립니다.")
        old_chunks, new_chunks = inline_diff_blocks(old, new)
        self.assertEqual("".join(chunk.text for chunk in old_chunks if chunk.changed), "59")
        self.assertEqual("".join(chunk.text for chunk in new_chunks if chunk.changed), "68")
        self.assertTrue(all(chunk.rects for chunk in old_chunks + new_chunks if chunk.changed))

    def test_inline_change_detects_numbers(self):
        old, new = inline_diff("평가 기간은 30일입니다.", "평가 기간은 40일입니다.")
        self.assertEqual("".join(c.text for c in old if c.changed), "30")
        self.assertEqual("".join(c.text for c in new if c.changed), "40")


if __name__ == "__main__":
    unittest.main()
