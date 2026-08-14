import unittest

from guide_comparison.diff.models import DiffStatus, TableBlock
from guide_comparison.diff.table_diff import compare_tables


class TableDiffTests(unittest.TestCase):
    def test_row_added(self):
        rows = compare_tables(TableBlock([["Item", "Limit"], ["A", "3"]]), TableBlock([["Item", "Limit"], ["A", "3"], ["B", "2"]]))
        self.assertEqual(rows[-1].status, DiffStatus.ADDED)
        self.assertIsNone(rows[-1].old_cells)

    def test_row_removed(self):
        rows = compare_tables(TableBlock([["A", "3"], ["B", "2"]]), TableBlock([["A", "3"]]))
        self.assertEqual(rows[-1].status, DiffStatus.REMOVED)

    def test_cell_modified(self):
        rows = compare_tables(TableBlock([["Manufacture", "3 days"]]), TableBlock([["Manufacture", "5 days"]]))
        self.assertEqual(rows[0].status, DiffStatus.MODIFIED)
        self.assertEqual(rows[0].changed_old_cells, {1})

    def test_multiple_cells_and_empty_cell(self):
        rows = compare_tables(TableBlock([["A", "", "3"]]), TableBlock([["B", "", "5"]]))
        self.assertEqual(rows[0].changed_old_cells, {0, 2})

    def test_merged_cell_representation_does_not_crash(self):
        rows = compare_tables(TableBlock([["Merged", "Merged", "3"]]), TableBlock([["Merged", "Merged", "4"]]))
        self.assertEqual(rows[0].status, DiffStatus.MODIFIED)


if __name__ == "__main__":
    unittest.main()

