from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStatusBar, QVBoxLayout, QWidget,
)

from guide_comparison.diff.models import DiffStatus, ParsedDocument
from guide_comparison.workers import CompareWorker

from .comparison_view import ComparisonRenderer, SyncGutter
from .document_pane import DocumentPane


log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guide Comparison")
        self.resize(1280, 820)
        self.old_path: Path | None = None
        self.new_path: Path | None = None
        self._thread: QThread | None = None
        self._pending_compare = False
        self._change_cursor = -1
        self._build_ui()

    def _build_ui(self):
        central = QWidget(); root = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        self.compare_button = QPushButton("Compare")
        self.swap_button = QPushButton("Swap OLD ↔ NEW")
        self.previous_button = QPushButton("← Previous Change")
        self.next_button = QPushButton("Next Change →")
        self.summary = QLabel("Added: 0    Removed: 0    Modified: 0")
        self.summary.setObjectName("summary")
        toolbar.addWidget(self.compare_button)
        toolbar.addWidget(self.swap_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.summary)
        toolbar.addStretch(1)
        toolbar.addWidget(self.previous_button); toolbar.addWidget(self.next_button)
        root.addLayout(toolbar)
        body = QHBoxLayout(); body.setSpacing(0)
        self.old_pane = DocumentPane("OLD")
        self.new_pane = DocumentPane("NEW")
        self.gutter = SyncGutter()
        body.addWidget(self.old_pane, 1); body.addWidget(self.gutter); body.addWidget(self.new_pane, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.renderer = ComparisonRenderer(self.old_pane, self.new_pane, self.gutter)
        self.old_pane.fileSelected.connect(lambda path: self.set_file("old", path))
        self.new_pane.fileSelected.connect(lambda path: self.set_file("new", path))
        self.old_pane.select_button.clicked.connect(lambda: self.select_file("old"))
        self.new_pane.select_button.clicked.connect(lambda: self.select_file("new"))
        self.old_pane.clearRequested.connect(lambda: self.clear_file("old"))
        self.new_pane.clearRequested.connect(lambda: self.clear_file("new"))
        self.swap_button.clicked.connect(self.swap_files)
        self.compare_button.clicked.connect(self.compare_requested)
        self.previous_button.clicked.connect(lambda: self.navigate_change(-1))
        self.next_button.clicked.connect(lambda: self.navigate_change(1))
        self._set_navigation_enabled(False)

    def select_file(self, side: str):
        filename, _ = QFileDialog.getOpenFileName(self, f"Select {side.upper()} document", "", "Documents (*.docx *.pdf)")
        if filename:
            self.set_file(side, Path(filename))

    def set_file(self, side: str, path: Path):
        if path.suffix.lower() not in {".docx", ".pdf"}:
            QMessageBox.warning(self, "Unsupported file", "Unsupported file type.\n\nSupported:\nDOCX\nPDF")
            return
        if side == "old":
            self.old_path = path; self.old_pane.set_document(path, path.suffix[1:].upper())
            log.info("Old document loaded: %s", path)
        else:
            self.new_path = path; self.new_pane.set_document(path, path.suffix[1:].upper())
            log.info("New document loaded: %s", path)
        self.compare_if_ready()

    def clear_file(self, side: str):
        if side == "old":
            self.old_path = None; self.old_pane.set_document(None)
        else:
            self.new_path = None; self.new_pane.set_document(None)
        self.old_pane.clear_content(); self.new_pane.clear_content()
        self.summary.setText("Added: 0    Removed: 0    Modified: 0")
        self._set_navigation_enabled(False)

    def swap_files(self):
        self.old_path, self.new_path = self.new_path, self.old_path
        self.old_pane.set_document(self.old_path, self.old_path.suffix[1:].upper() if self.old_path else "")
        self.new_pane.set_document(self.new_path, self.new_path.suffix[1:].upper() if self.new_path else "")
        self.compare_if_ready()

    def compare_requested(self):
        if not (self.old_path and self.new_path):
            QMessageBox.information(self, "Select two documents", "Select both an OLD and a NEW document first.")
            return
        self.compare_if_ready()

    def compare_if_ready(self):
        if not (self.old_path and self.new_path):
            return
        if self._thread and self._thread.isRunning():
            self._pending_compare = True
            self.statusBar().showMessage("A newer selection is queued...")
            return
        old_path, new_path = self.old_path, self.new_path
        self._thread = QThread(self)
        worker = CompareWorker(old_path, new_path)
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.progress.connect(self.statusBar().showMessage)
        worker.succeeded.connect(self.comparison_ready)
        worker.failed.connect(self.comparison_failed)
        worker.finished.connect(self._thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker_finished)
        self.swap_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self._thread.start()

    def _worker_finished(self):
        self._thread = None
        self.swap_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        if self._pending_compare:
            self._pending_compare = False
            self.compare_if_ready()

    def comparison_ready(self, old: ParsedDocument, new: ParsedDocument, pairs):
        if old.path != self.old_path or new.path != self.new_path:
            return
        self.old_pane.set_document(old.path, f"{old.page_count} pages" if old.page_count is not None else "DOCX")
        self.new_pane.set_document(new.path, f"{new.page_count} pages" if new.page_count is not None else "DOCX")
        self.renderer.render(pairs)
        counts = Counter(pair.status for pair in pairs)
        self.summary.setText(f"Added: {counts[DiffStatus.ADDED]}    Removed: {counts[DiffStatus.REMOVED]}    Modified: {counts[DiffStatus.MODIFIED]}")
        self._change_cursor = -1
        self._set_navigation_enabled(bool(self.renderer.change_positions))
        self.statusBar().showMessage("Comparison complete.", 5000)
        log.info("Comparison complete")
        warnings = [warning for warning in (old.warning, new.warning) if warning]
        if warnings:
            QMessageBox.information(self, "Limited text extraction", "\n\n".join(warnings))

    def comparison_failed(self, message: str):
        self.statusBar().showMessage("Comparison failed.")
        QMessageBox.critical(self, "Unable to compare documents", message)

    def navigate_change(self, delta: int):
        positions = self.renderer.change_positions
        if not positions:
            return
        self._change_cursor = (self._change_cursor + delta) % len(positions)
        self.renderer.navigate(positions[self._change_cursor])

    def _set_navigation_enabled(self, enabled: bool):
        self.previous_button.setEnabled(enabled); self.next_button.setEnabled(enabled)

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.quit(); self._thread.wait(2000)
        super().closeEvent(event)
