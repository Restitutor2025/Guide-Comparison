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

    def test_middle_insertions_realign_tail(self):
        pairs = compare_documents(document(list("ABCDEFG")), document(["A", "B", "C", "NEW 1", "NEW 2", "NEW 3", "D", "E", "F", "G"]))
        self.assertEqual(sum(p.status == DiffStatus.ADDED for p in pairs), 3)
        self.assertTrue(all(p.status == DiffStatus.UNCHANGED for p in pairs[-4:]))

    def test_middle_deletions_realign_tail(self):
        pairs = compare_documents(document(["A", "B", "DELETE 1", "DELETE 2", "DELETE 3", "C", "D"]), document(["A", "B", "C", "D"]))
        self.assertEqual(sum(p.status == DiffStatus.REMOVED for p in pairs), 3)
        self.assertTrue(all(p.status == DiffStatus.UNCHANGED for p in pairs[-2:]))


if __name__ == "__main__":
    unittest.main()

