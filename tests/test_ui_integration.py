import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
import pymupdf as fitz
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from guide_comparison.diff.models import AlignedPair, DiffStatus, InlineChunk, ParsedDocument, TextBlock
from guide_comparison.diff.document_diff import compare_documents
from guide_comparison.parsers import parse_document
from guide_comparison.ui.main_window import MainWindow


class UiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate, timeout=8.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            QTest.qWait(10)
        return False

    @staticmethod
    def make_pdf(path: Path, lines: list[str]):
        document = fitz.open()
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + index * 28), line)
        document.save(path)
        document.close()

    @staticmethod
    def make_multipage_pdf(path: Path, pages: int, label: str = "Page"):
        document = fitz.open()
        for page_number in range(1, pages + 1):
            page = document.new_page()
            page.insert_text((72, 72), f"{label} {page_number}")
        document.save(path)
        document.close()

    def test_background_comparison_reaches_the_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.pdf", Path(folder) / "new.pdf"
            self.make_pdf(old_path, ["Evaluation period is 30 days."])
            self.make_pdf(new_path, ["Evaluation period is 40 days."])
            window = MainWindow(); window.show()
            window.set_file("old", old_path); window.set_file("new", new_path)
            self.assertIsNotNone(window._worker)
            self.assertTrue(self.wait_until(lambda: window._thread is None and window.statusBar().currentMessage() == "Comparison complete."))
            self.assertEqual(window.differences_label.text(), "Differences 1/1")
            self.assertEqual(window._difference_cursor, 0)
            self.assertEqual(len(window.renderer.difference_targets), 1)
            window.close()

    def test_original_pages_render_without_blank_counterparts(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.pdf", Path(folder) / "new.pdf"
            self.make_pdf(old_path, ["Keep"])
            self.make_pdf(new_path, ["Keep", "New content"])
            old, new = parse_document(old_path), parse_document(new_path)
            pairs = compare_documents(old, new)

            window = MainWindow(); window.resize(1500, 700); window.show()
            finished = []
            window.renderer.renderingFinished.connect(lambda: finished.append(True))
            window.renderer.render(old, new, pairs)
            self.assertTrue(self.wait_until(lambda: bool(finished)))
            self.assertEqual(len(window.renderer.old_page_widgets), 0)
            self.assertEqual(len(window.renderer.new_page_widgets), 1)
            self.assertEqual(sum(map(len, window.renderer.old_highlights.values())), 0)
            self.assertGreater(sum(map(len, window.renderer.new_highlights.values())), 0)
            self.assertEqual(len(window.renderer.difference_targets), 1)

            new_page = window.renderer.new_page_widgets[0]
            point_on_page = window.new_pane.scroll.viewport().mapFromGlobal(
                new_page.mapToGlobal(new_page.rect().center())
            )
            self.assertTrue(window.new_pane.scroll._over_document_page(point_on_page))
            self.assertFalse(window.new_pane.scroll._over_document_page(new_page.pos() - new_page.pos()))
            window.close()

    def test_unchanged_pages_are_not_added_to_the_rendered_stacks(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.pdf", Path(folder) / "new.pdf"
            old_document = fitz.open()
            new_document = fitz.open()
            old_lines = ["Same introduction", "Old requirement", "Same appendix"]
            new_lines = ["Same introduction", "New requirement", "Same appendix"]
            for old_text, new_text in zip(old_lines, new_lines):
                old_page = old_document.new_page()
                old_page.insert_text((72, 72), old_text)
                new_page = new_document.new_page()
                new_page.insert_text((72, 72), new_text)
            old_document.save(old_path); old_document.close()
            new_document.save(new_path); new_document.close()

            old, new = parse_document(old_path), parse_document(new_path)
            window = MainWindow(); window.resize(1200, 700); window.show()
            window.renderer.render(old, new, compare_documents(old, new))
            QTest.qWait(50)

            self.assertEqual([widget.page_index + 1 for widget in window.renderer.old_page_widgets], [2])
            self.assertEqual([widget.page_index + 1 for widget in window.renderer.new_page_widgets], [2])
            self.assertNotIn(1, [widget.page_index + 1 for widget in window.renderer.old_page_widgets])
            self.assertNotIn(3, [widget.page_index + 1 for widget in window.renderer.new_page_widgets])
            window.close()

    def test_first_arrow_click_moves_from_initial_difference(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.pdf", Path(folder) / "new.pdf"
            old_document = fitz.open()
            new_document = fitz.open()
            for old_text, new_text in (
                ("Old first requirement", "New first requirement"),
                ("Same middle page", "Same middle page"),
                ("Old last requirement", "New last requirement"),
            ):
                old_page = old_document.new_page(); old_page.insert_text((72, 72), old_text)
                new_page = new_document.new_page(); new_page.insert_text((72, 72), new_text)
            old_document.save(old_path); old_document.close()
            new_document.save(new_path); new_document.close()

            window = MainWindow(); window.show()
            window.set_file("old", old_path); window.set_file("new", new_path)
            self.assertTrue(self.wait_until(
                lambda: window._thread is None
                and window.statusBar().currentMessage() == "Comparison complete."
            ))
            self.assertEqual(window.differences_label.text(), "Differences 1/2")
            self.assertEqual(window._difference_cursor, 0)
            self.assertTrue(window.next_difference_button.isEnabled())

            QTest.mouseClick(window.next_difference_button, Qt.MouseButton.LeftButton)
            self.assertEqual(window._difference_cursor, 1)
            self.assertEqual(window.differences_label.text(), "Differences 2/2")
            QTest.mouseClick(window.previous_difference_button, Qt.MouseButton.LeftButton)
            self.assertEqual(window._difference_cursor, 0)
            self.assertEqual(window.differences_label.text(), "Differences 1/2")
            window.close()

    def test_difference_targets_group_changes_by_page(self):
        pairs = [
            AlignedPair(TextBlock("A", page=1), TextBlock("B", page=1), DiffStatus.MODIFIED),
            AlignedPair(TextBlock("C", page=1), TextBlock("D", page=1), DiffStatus.MODIFIED),
            AlignedPair(None, TextBlock("Added", page=2), DiffStatus.ADDED),
            AlignedPair(TextBlock("Removed", page=3), None, DiffStatus.REMOVED),
        ]
        window = MainWindow()
        targets = window.renderer._build_difference_targets(pairs)
        self.assertEqual([(target.old_page, target.new_page) for target in targets], [(1, 1), (None, 2), (3, None)])
        window.close()

    def test_difference_navigation_buttons_wrap_and_empty_result_shows_message(self):
        window = MainWindow(); window.show()
        with patch.object(QMessageBox, "information") as information:
            window.show_next_difference()
            information.assert_called_once_with(window, "Differences", "변경점이 없습니다")

        window.renderer.difference_targets = [
            window.renderer._build_difference_targets([
                AlignedPair(TextBlock("A", page=1), TextBlock("B", page=1), DiffStatus.MODIFIED)
            ])[0]
        ]
        window._difference_cursor = 0
        window.show_next_difference()
        self.assertEqual(window._difference_cursor, 0)
        self.assertEqual(window.differences_label.text(), "Differences 1/1")
        window.show_previous_difference()
        self.assertEqual(window._difference_cursor, 0)
        self.assertEqual(window.differences_label.text(), "Differences 1/1")
        self.assertFalse(hasattr(window.differences_label, "clicked"))
        window.close()

    def test_difference_navigation_moves_in_both_directions(self):
        window = MainWindow(); window.show()
        window.renderer.difference_targets = window.renderer._build_difference_targets([
            AlignedPair(TextBlock("A", page=1), TextBlock("B", page=1), DiffStatus.MODIFIED),
            AlignedPair(TextBlock("C", page=2), TextBlock("D", page=2), DiffStatus.MODIFIED),
        ])
        with patch.object(window.renderer, "navigate_difference") as navigate:
            window.show_next_difference()
            navigate.assert_called_with(0)
            window.show_next_difference()
            navigate.assert_called_with(1)
            window.show_previous_difference()
            navigate.assert_called_with(0)
        self.assertEqual(window.differences_label.text(), "Differences 1/2")
        window.close()

    def test_page_drag_is_independent_and_margin_drag_is_synchronized(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.pdf", Path(folder) / "new.pdf"
            self.make_multipage_pdf(old_path, 3, "Old page")
            self.make_multipage_pdf(new_path, 3, "New page")
            old, new = parse_document(old_path), parse_document(new_path)
            window = MainWindow(); window.resize(1200, 700); window.show()
            window.renderer.render(old, new, compare_documents(old, new))
            QTest.qWait(50)

            old_scroll, new_scroll = window.old_pane.scroll, window.new_pane.scroll
            old_scroll.verticalScrollBar().setValue(200)
            new_scroll.verticalScrollBar().setValue(200)
            page = window.renderer.old_page_widgets[0]
            center = page.rect().center()
            QTest.mousePress(page, Qt.MouseButton.LeftButton, pos=center)
            QTest.mouseMove(page, center + QPoint(0, -50), 20)
            QTest.mouseRelease(page, Qt.MouseButton.LeftButton, pos=center + QPoint(0, -50))
            self.assertEqual(old_scroll.verticalScrollBar().value(), 250)
            self.assertEqual(new_scroll.verticalScrollBar().value(), 200)

            margin = QPoint(2, 100)
            QTest.mousePress(old_scroll.viewport(), Qt.MouseButton.LeftButton, pos=margin)
            QTest.mouseMove(old_scroll.viewport(), margin + QPoint(0, -50), 20)
            QTest.mouseRelease(old_scroll.viewport(), Qt.MouseButton.LeftButton, pos=margin + QPoint(0, -50))
            self.assertEqual(old_scroll.verticalScrollBar().value(), 300)
            self.assertEqual(new_scroll.verticalScrollBar().value(), 250)
            window.close()

    def test_close_waits_for_running_worker(self):
        def slow_parse(path):
            time.sleep(0.1)
            return ParsedDocument(Path(path), [TextBlock("content")])

        with patch("guide_comparison.workers.compare_worker.parse_document", side_effect=slow_parse):
            window = MainWindow(); window.show()
            window.set_file("old", Path("old.pdf")); window.set_file("new", Path("new.pdf"))
            self.assertIsNotNone(window._thread)
            window.close()
            self.assertTrue(window._close_when_finished)
            self.assertFalse(window.isVisible())
            self.assertTrue(self.wait_until(lambda: window._thread is None))


if __name__ == "__main__":
    unittest.main()
