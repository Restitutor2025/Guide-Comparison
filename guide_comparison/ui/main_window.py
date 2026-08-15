from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStatusBar, QVBoxLayout, QWidget,
)

from guide_comparison.diff.models import ParsedDocument
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
        self._worker: CompareWorker | None = None
        self._pending_compare = False
        self._close_when_finished = False
        self._difference_cursor = -1
        self._build_ui()

    def _build_ui(self):
        central = QWidget(); root = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        left_controls = QWidget()
        left_layout = QHBoxLayout(left_controls)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.compare_button = QPushButton("Compare")
        self.swap_button = QPushButton("Swap OLD ↔ NEW")
        left_layout.addWidget(self.compare_button)
        left_layout.addWidget(self.swap_button)

        difference_controls = QWidget()
        difference_layout = QVBoxLayout(difference_controls)
        difference_layout.setContentsMargins(0, 0, 0, 0)
        difference_layout.setSpacing(3)
        self.differences_label = QLabel("Differences 0/0")
        self.differences_label.setObjectName("differencesLabel")
        self.differences_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        difference_layout.addWidget(self.differences_label)
        difference_buttons = QHBoxLayout()
        difference_buttons.setContentsMargins(0, 0, 0, 0)
        difference_buttons.setSpacing(5)
        self.previous_difference_button = QPushButton("↑")
        self.previous_difference_button.setObjectName("differenceNavigationButton")
        self.previous_difference_button.setToolTip("Previous changed page")
        self.previous_difference_button.setAccessibleName("Previous changed page")
        self.next_difference_button = QPushButton("↓")
        self.next_difference_button.setObjectName("differenceNavigationButton")
        self.next_difference_button.setToolTip("Next changed page")
        self.next_difference_button.setAccessibleName("Next changed page")
        for button in (self.previous_difference_button, self.next_difference_button):
            button.setFixedSize(38, 28)
            button.setEnabled(False)
        difference_buttons.addWidget(self.previous_difference_button)
        difference_buttons.addWidget(self.next_difference_button)
        difference_layout.addLayout(difference_buttons)

        right_balance = QWidget()
        right_balance.setFixedWidth(left_controls.sizeHint().width())
        toolbar.addWidget(left_controls)
        toolbar.addStretch(1)
        toolbar.addWidget(difference_controls, 0, Qt.AlignmentFlag.AlignTop)
        toolbar.addStretch(1)
        toolbar.addWidget(right_balance)
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
        self.renderer.renderingFinished.connect(self._rendering_finished)
        self.old_pane.fileSelected.connect(lambda path: self.set_file("old", path))
        self.new_pane.fileSelected.connect(lambda path: self.set_file("new", path))
        self.old_pane.select_button.clicked.connect(lambda: self.select_file("old"))
        self.new_pane.select_button.clicked.connect(lambda: self.select_file("new"))
        self.old_pane.clearRequested.connect(lambda: self.clear_file("old"))
        self.new_pane.clearRequested.connect(lambda: self.clear_file("new"))
        self.swap_button.clicked.connect(self.swap_files)
        self.compare_button.clicked.connect(self.compare_requested)
        self.previous_difference_button.clicked.connect(self.show_previous_difference)
        self.next_difference_button.clicked.connect(self.show_next_difference)

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
        self.renderer.cancel_render()
        self.old_pane.clear_content(); self.new_pane.clear_content()
        self._difference_cursor = -1
        self._set_difference_controls("Differences 0/0", False)

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
            self._thread.requestInterruption()
            self.statusBar().showMessage("A newer selection is queued...")
            return
        old_path, new_path = self.old_path, self.new_path
        self.renderer.cancel_render()
        self._difference_cursor = -1
        self._set_difference_controls("Differences …", False)
        self._thread = QThread(self)
        self._worker = CompareWorker(old_path, new_path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.statusBar().showMessage)
        self._worker.succeeded.connect(self.comparison_ready)
        self._worker.failed.connect(self.comparison_failed)
        self._worker.cancelled.connect(lambda: self.statusBar().showMessage("Comparison cancelled."))
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._worker_finished)
        self.swap_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self._thread.start()

    def _worker_finished(self):
        self._thread = None
        self._worker = None
        self.swap_button.setEnabled(True)
        self.compare_button.setEnabled(True)
        if self._close_when_finished:
            QTimer.singleShot(0, self.close)
            return
        if self._pending_compare:
            self._pending_compare = False
            self.compare_if_ready()

    def comparison_ready(self, old: ParsedDocument, new: ParsedDocument, pairs):
        if old.path != self.old_path or new.path != self.new_path:
            return
        self.old_pane.set_document(old.path, f"{old.page_count} pages" if old.page_count is not None else "DOCX")
        self.new_pane.set_document(new.path, f"{new.page_count} pages" if new.page_count is not None else "DOCX")
        self.renderer.render(old, new, pairs)
        self._difference_cursor = -1
        self.statusBar().showMessage("Rendering...")
        warnings = [warning for warning in (old.warning, new.warning) if warning]
        if warnings:
            QMessageBox.information(self, "Limited text extraction", "\n\n".join(warnings))

    def _rendering_finished(self):
        target_count = len(self.renderer.difference_targets)
        if target_count:
            self._difference_cursor = 0
            self._set_difference_controls(f"Differences 1/{target_count}", True)
            self.renderer.navigate_difference(0)
        else:
            self._difference_cursor = -1
            self._set_difference_controls("Differences 0/0", True)
        self.statusBar().showMessage("Comparison complete.", 5000)
        log.info("Comparison complete")

    def comparison_failed(self, old_path: Path, new_path: Path, message: str):
        if old_path != self.old_path or new_path != self.new_path or self._close_when_finished:
            return
        self.statusBar().showMessage("Comparison failed.")
        QMessageBox.critical(self, "Unable to compare documents", message)

    def _set_difference_controls(self, text: str, enabled: bool):
        self.differences_label.setText(text)
        self.previous_difference_button.setEnabled(enabled)
        self.next_difference_button.setEnabled(enabled)

    def _navigate_difference(self, index: int):
        targets = self.renderer.difference_targets
        self._difference_cursor = index % len(targets)
        self.renderer.navigate_difference(self._difference_cursor)
        self.differences_label.setText(
            f"Differences {self._difference_cursor + 1}/{len(targets)}"
        )

    def _difference_targets_or_warn(self):
        targets = self.renderer.difference_targets
        if not targets:
            QMessageBox.information(self, "Differences", "변경점이 없습니다")
            return None
        return targets

    def show_previous_difference(self):
        targets = self._difference_targets_or_warn()
        if targets is None:
            return
        previous_index = len(targets) - 1 if self._difference_cursor < 0 else self._difference_cursor - 1
        self._navigate_difference(previous_index)

    def show_next_difference(self):
        targets = self._difference_targets_or_warn()
        if targets is None:
            return
        self._navigate_difference(self._difference_cursor + 1)

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._close_when_finished = True
            self._pending_compare = False
            self._thread.requestInterruption()
            self.hide()
            self.statusBar().showMessage("Finishing document processing before exit...")
            event.ignore()
            return
        self.renderer.cancel_render()
        super().closeEvent(event)
