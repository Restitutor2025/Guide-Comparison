import unittest

from guide_comparison.diff.models import DiffStatus, TextBlock
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

    def test_changed_digit_does_not_expand_into_overlapping_korean_unit(self):
        old = TextBlock(
            "3개월",
            chars=[
                ("3", 0.0, 0.0, 1.1, 1.0),
                ("개", 1.0, 0.0, 2.0, 1.0),
                ("월", 2.0, 0.0, 3.0, 1.0),
            ],
        )
        new = TextBlock(
            "2개월",
            chars=[
                ("2", 0.0, 0.0, 1.1, 1.0),
                ("개", 1.0, 0.0, 2.0, 1.0),
                ("월", 2.0, 0.0, 3.0, 1.0),
            ],
        )

        old_chunks, new_chunks = inline_diff_blocks(old, new)
        old_change = next(chunk for chunk in old_chunks if chunk.changed)
        new_change = next(chunk for chunk in new_chunks if chunk.changed)

        self.assertEqual(old_change.text, "3")
        self.assertEqual(new_change.text, "2")
        self.assertEqual(old_change.rects, [(0.0, 0.0, 1.1, 1.0)])
        self.assertEqual(new_change.rects, [(0.0, 0.0, 1.1, 1.0)])

    def test_single_changed_digit_expands_only_to_its_multi_digit_value(self):
        old = self.block_with_chars("30일")
        new = self.block_with_chars("40일")

        old_chunks, new_chunks = inline_diff_blocks(old, new)
        old_change = next(chunk for chunk in old_chunks if chunk.changed)
        new_change = next(chunk for chunk in new_chunks if chunk.changed)

        self.assertEqual(old_change.text, "3")
        self.assertEqual(new_change.text, "4")
        self.assertEqual(old_change.rects, [(0.0, 0.0, 2.0, 1.0)])
        self.assertEqual(new_change.rects, [(0.0, 0.0, 2.0, 1.0)])

    def test_inline_insertions_and_deletions_have_directional_status(self):
        deleted, _ = inline_diff("Keep deleted tail", "Keep")
        _, added = inline_diff("Keep", "Keep added tail")
        replaced_old, replaced_new = inline_diff("Keep old", "Keep new")
        self.assertIn(DiffStatus.REMOVED, {chunk.status for chunk in deleted if chunk.changed})
        self.assertIn(DiffStatus.ADDED, {chunk.status for chunk in added if chunk.changed})
        self.assertIn(DiffStatus.MODIFIED, {chunk.status for chunk in replaced_old + replaced_new if chunk.changed})

    def test_block_diff_does_not_anchor_a_long_replacement_on_one_korean_character(self):
        old = self.block_with_chars("품목으로서 제출 자료를 모두 제출한 경우")
        new = self.block_with_chars("품목으로서 규칙 제4조에 따른 자료를 제출한 경우")
        old_chunks, new_chunks = inline_diff_blocks(old, new)
        single_character = next(chunk for chunk in old_chunks if chunk.changed and chunk.text == "출")
        self.assertGreater(sum(rect[2] - rect[0] for rect in single_character.rects), 1.0)
        self.assertIn("규칙", "".join(chunk.text for chunk in new_chunks if chunk.changed))


if __name__ == "__main__":
    unittest.main()
