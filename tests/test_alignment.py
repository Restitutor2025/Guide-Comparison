import unittest
from pathlib import Path

from guide_comparison.diff.document_diff import compare_documents
from guide_comparison.diff.models import DiffStatus, ParsedDocument, TextBlock


def document(lines):
    return ParsedDocument(Path("test.docx"), [TextBlock(line) for line in lines])


class AlignmentTests(unittest.TestCase):
    def test_paragraph_added(self):
        pairs = compare_documents(document(["A", "B", "C"]), document(["A", "NEW", "B", "C"]))
        self.assertEqual([p.status for p in pairs], [DiffStatus.UNCHANGED, DiffStatus.ADDED, DiffStatus.UNCHANGED, DiffStatus.UNCHANGED])
        self.assertIsNone(pairs[1].old_block)

    def test_paragraph_removed(self):
        pairs = compare_documents(document(["A", "REMOVE", "B", "C"]), document(["A", "B", "C"]))
        self.assertEqual([p.status for p in pairs], [DiffStatus.UNCHANGED, DiffStatus.REMOVED, DiffStatus.UNCHANGED, DiffStatus.UNCHANGED])

    def test_paragraph_modified(self):
        pairs = compare_documents(document(["평가 기간은 30일입니다."]), document(["평가 기간은 40일입니다."]))
        self.assertEqual(pairs[0].status, DiffStatus.MODIFIED)
        self.assertIn("30", "".join(c.text for c in pairs[0].old_inline if c.changed))
        self.assertIn("40", "".join(c.text for c in pairs[0].new_inline if c.changed))

    def test_layout_only_spacing_is_unchanged(self):
        pairs = compare_documents(document(["바이오의약품 사전 GMP 평가"]), document(["바이오의약품 사전GMP평가"]))
        self.assertEqual(pairs[0].status, DiffStatus.UNCHANGED)

    def test_small_numeric_change_in_long_text_is_not_hidden(self):
        prefix = "허가 신청에 필요한 자료를 검토하고 평가 기간을 준수해야 합니다. " * 4
        pairs = compare_documents(document([prefix + "30일"]), document([prefix + "40일"]))
        self.assertEqual(pairs[0].status, DiffStatus.MODIFIED)

    def test_middle_insertions_realign_tail(self):
        pairs = compare_documents(document(list("ABCDEFG")), document(["A", "B", "C", "NEW 1", "NEW 2", "NEW 3", "D", "E", "F", "G"]))
        self.assertEqual(sum(p.status == DiffStatus.ADDED for p in pairs), 3)
        self.assertTrue(all(p.status == DiffStatus.UNCHANGED for p in pairs[-4:]))

    def test_middle_deletions_realign_tail(self):
        pairs = compare_documents(document(["A", "B", "DELETE 1", "DELETE 2", "DELETE 3", "C", "D"]), document(["A", "B", "C", "D"]))
        self.assertEqual(sum(p.status == DiffStatus.REMOVED for p in pairs), 3)
        self.assertTrue(all(p.status == DiffStatus.UNCHANGED for p in pairs[-2:]))

    def test_unique_moved_paragraph_is_not_reported_as_removed_and_added(self):
        moved = "A sufficiently long paragraph that moves between sections."
        pairs = compare_documents(
            document(["Heading A", moved, "Heading B", "Tail"]),
            document(["Heading A", "Heading B", moved, "Tail"]),
        )
        moved_pair = next(pair for pair in pairs if pair.old_block and pair.old_block.text == moved)
        self.assertEqual(moved_pair.status, DiffStatus.UNCHANGED)
        self.assertEqual(moved_pair.new_block.text, moved)
        self.assertFalse(any(pair.status == DiffStatus.ADDED and pair.new_block.text == moved for pair in pairs))

    def test_unique_structural_path_matches_a_heavily_rewritten_item_after_insertion(self):
        old_item = TextBlock(
            "② 기존 패키지 구성품 관련 평가 기준",
            "list",
            structure_path=("heading:number:3", "heading:box:평가사항", "item:②"),
            marker="②",
        )
        unchanged_tail = TextBlock(
            "③ 변경되지 않은 다음 평가 기준",
            "list",
            structure_path=("heading:number:3", "heading:box:평가사항", "item:③"),
            marker="③",
        )
        inserted = TextBlock(
            "※ 새로 추가된 예외 조건",
            "list",
            structure_path=("heading:number:3", "heading:box:평가사항", "item:※"),
            marker="※",
        )
        rewritten_item = TextBlock(
            "② 첨부용제를 포함하는 품목을 새롭게 심사한다",
            "list",
            structure_path=old_item.structure_path,
            marker="②",
        )

        pairs = compare_documents(
            ParsedDocument(Path("old.pdf"), [old_item, unchanged_tail]),
            ParsedDocument(Path("new.pdf"), [inserted, rewritten_item, unchanged_tail]),
        )

        matched = next(pair for pair in pairs if pair.old_block is old_item)
        self.assertIs(matched.new_block, rewritten_item)
        self.assertEqual(matched.status, DiffStatus.MODIFIED)
        self.assertEqual(sum(pair.status == DiffStatus.ADDED for pair in pairs), 1)
        self.assertIs(next(pair.new_block for pair in pairs if pair.status == DiffStatus.ADDED), inserted)

    def test_duplicate_structural_paths_do_not_force_ambiguous_matches(self):
        duplicate_path = ("heading:number:3", "item:①")
        old = ParsedDocument(Path("old.pdf"), [
            TextBlock("완전히 오래된 첫 문구", structure_path=duplicate_path),
            TextBlock("완전히 오래된 둘째 문구", structure_path=duplicate_path),
        ])
        new = ParsedDocument(Path("new.pdf"), [
            TextBlock("서로 무관한 신규 알파", structure_path=duplicate_path),
            TextBlock("서로 무관한 신규 베타", structure_path=duplicate_path),
        ])

        pairs = compare_documents(old, new)

        self.assertFalse(any(pair.status == DiffStatus.MODIFIED for pair in pairs))
        self.assertEqual(sum(pair.status == DiffStatus.REMOVED for pair in pairs), 2)
        self.assertEqual(sum(pair.status == DiffStatus.ADDED for pair in pairs), 2)

    def test_same_text_still_matches_when_item_numbers_are_renumbered(self):
        text = "패키지 구성품이 추가된 경우"
        old = TextBlock(text, "list", structure_path=("heading:number:3", "item:②"), marker="②")
        new = TextBlock(text, "list", structure_path=("heading:number:3", "item:③"), marker="③")
        pairs = compare_documents(
            ParsedDocument(Path("old.pdf"), [old]),
            ParsedDocument(Path("new.pdf"), [new]),
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].status, DiffStatus.UNCHANGED)

    def test_reordered_short_table_cells_are_not_reported_as_added_and_removed(self):
        old = ParsedDocument(Path("old.pdf"), [
            TextBlock("Before"),
            TextBlock("A", "table_cell", page=1, rects=[(10, 200, 20, 210)]),
            TextBlock("국가", "table_cell", page=1, rects=[(30, 200, 50, 210)]),
            TextBlock("After"),
        ])
        new = ParsedDocument(Path("new.pdf"), [
            TextBlock("A", "table_cell", page=1, rects=[(10, 100, 20, 110)]),
            TextBlock("국가", "table_cell", page=1, rects=[(30, 100, 50, 110)]),
            TextBlock("Before"),
            TextBlock("After"),
        ])

        pairs = compare_documents(old, new)

        table_pairs = [
            pair for pair in pairs
            if getattr(pair.old_block, "block_type", None) == "table_cell"
            or getattr(pair.new_block, "block_type", None) == "table_cell"
        ]
        self.assertEqual(len(table_pairs), 2)
        self.assertTrue(all(pair.status == DiffStatus.UNCHANGED for pair in table_pairs))

    def test_split_table_cell_with_same_combined_text_is_layout_only(self):
        old = ParsedDocument(Path("old.pdf"), [
            TextBlock("라벨링 →조립 →2차포장출하승인", "table_cell", page=1),
        ])
        new = ParsedDocument(Path("new.pdf"), [
            TextBlock("라벨링 →조립 →2차포장", "table_cell", page=1),
            TextBlock("출하승인", "table_cell", page=1),
        ])

        pairs = compare_documents(old, new)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].status, DiffStatus.UNCHANGED)

    def test_moved_cross_page_split_table_cells_are_layout_only(self):
        old = ParsedDocument(Path("old.pdf"), [
            TextBlock("라벨링 →조립 →2차포장", "table_cell", page=6, rects=[(300, 200, 500, 220)]),
            TextBlock("출하승인", "table_cell", page=6, rects=[(510, 200, 580, 220)]),
            TextBlock("검토 및 평가", page=6),
        ])
        new = ParsedDocument(Path("new.pdf"), [
            TextBlock("새 평가표", page=6),
            TextBlock("라벨링 →조립 →2차포장출하승인", "table_cell", page=7, rects=[(300, 300, 580, 320)]),
            TextBlock("검토 및 평가", page=7),
        ])

        pairs = compare_documents(old, new)

        affected = [
            pair for pair in pairs
            if "라벨링" in (getattr(pair.old_block, "text", "") + getattr(pair.new_block, "text", ""))
            or "출하승인" in (getattr(pair.old_block, "text", "") + getattr(pair.new_block, "text", ""))
        ]
        self.assertEqual(len(affected), 1)
        self.assertEqual(affected[0].status, DiffStatus.UNCHANGED)

    def test_structured_rewritten_item_reconnects_across_nearby_pages(self):
        old_item = TextBlock(
            "ㅇ (기타사항) 융복합 의료제품 등의 GMP 평가 절차",
            "list",
            page=12,
            structure_path=("heading:number:3", "item:ㅇ", "item:ㅇ"),
            marker="ㅇ",
        )
        new_item = TextBlock(
            "ㅇ (기타) 융복합 의료제품 및 위·수탁 품목에 대한 GMP 평가",
            "list",
            page=10,
            structure_path=("heading:number:3", "item:ㅇ"),
            marker="ㅇ",
        )
        old = ParsedDocument(Path("old.pdf"), [TextBlock("stable anchor"), old_item])
        new = ParsedDocument(Path("new.pdf"), [new_item, TextBlock("stable anchor")])

        pairs = compare_documents(old, new)

        matched = next(pair for pair in pairs if pair.old_block is old_item)
        self.assertIs(matched.new_block, new_item)
        self.assertEqual(matched.status, DiffStatus.MODIFIED)
        self.assertFalse(any(pair.status in {DiffStatus.ADDED, DiffStatus.REMOVED} for pair in pairs))


if __name__ == "__main__":
    unittest.main()
