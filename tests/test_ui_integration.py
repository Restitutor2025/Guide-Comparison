import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from guide_comparison.diff.models import AlignedPair, DiffStatus, InlineChunk, ParsedDocument, TextBlock
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

    def test_background_comparison_reaches_the_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            old_path, new_path = Path(folder) / "old.docx", Path(folder) / "new.docx"
            old_doc = Document(); old_doc.add_paragraph("평가 기간은 30일입니다."); old_doc.save(old_path)
            new_doc = Document(); new_doc.add_paragraph("평가 기간은 40일입니다."); new_doc.save(new_path)
            window = MainWindow(); window.show()
            window.set_file("old", old_path); window.set_file("new", new_path)
            self.assertIsNotNone(window._worker)
            self.assertTrue(self.wait_until(lambda: window._thread is None and window.statusBar().currentMessage() == "Comparison complete."))
            self.assertEqual(window.summary.text(), "Added: 0    Removed: 0    Modified: 1")
            self.assertEqual(len(window.renderer.change_positions), 1)
            window.close()

    def test_wrapped_pair_heights_stay_aligned_after_resize(self):
        short = "OLD short sentence 30 days."
        long = ("NEW much longer sentence with many words " * 35) + "40 days."
        pairs = [
            AlignedPair(TextBlock("A"), TextBlock("A"), DiffStatus.UNCHANGED),
            AlignedPair(TextBlock(short), TextBlock(long), DiffStatus.MODIFIED, [InlineChunk(short, True)], [InlineChunk(long, True)]),
            AlignedPair(TextBlock("TAIL"), TextBlock("TAIL"), DiffStatus.UNCHANGED),
        ]
        window = MainWindow(); window.resize(1600, 700); window.show()
        finished = []
        window.renderer.renderingFinished.connect(lambda: finished.append(True))
        window.renderer.render(pairs)
        self.assertTrue(self.wait_until(lambda: bool(finished)))
        sync_token = window.renderer._height_sync_token
        window.resize(700, 500)
        self.assertTrue(self.wait_until(lambda: window.renderer._height_sync_token > sync_token and window.renderer._height_sync_index == len(window.renderer._pair_widgets)))
        for old_widget, new_widget in window.renderer._pair_widgets:
            self.assertEqual(old_widget.height(), new_widget.height())
            self.assertEqual(old_widget.y(), new_widget.y())
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
