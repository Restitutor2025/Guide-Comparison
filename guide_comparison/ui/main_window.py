from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

from guide_comparison.diff.models import ParsedDocument
from guide_comparison.workers import CompareWorker

from .comparison_view import ComparisonRenderer, SyncGutter
from .document_pane import DocumentPane
from .report_review_dialog import ReportReviewDialog


log = logging.getLogger(__name__)


class LoadingSpinner(QWidget):
    """A lightweight animated loading graphic with no external asset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(112, 112)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def start(self):
        self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(QPointF(self.width() / 2, self.height() / 2))
        painter.rotate(self._angle)
        for index in range(12):
            color = QColor("#245f9e")
            color.setAlpha(255 - index * 17)
            pen = QPen(color, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(0, -27, 0, -42)
            painter.rotate(30)


class LoadingOverlay(QFrame):
    """Block document controls and clearly report background processing."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("loadingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.spinner = LoadingSpinner(self)
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel("문서를 비교하고 있습니다…")
        self.label.setObjectName("loadingLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        layout.addStretch(1)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guide Comparison")
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1280, max(640, available.width() - 40)), min(960, max(640, available.height() - 40)))
        else:
            self.resize(1280, 960)
        self.old_path: Path | None = None
        self.new_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: CompareWorker | None = None
        self._pending_compare = False
        self._difference_cursor = -1
        self._report_pairs = []
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        self.interactive_content = QWidget(central)
        shell.addWidget(self.interactive_content)
        root = QVBoxLayout(self.interactive_content)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)
        command_bar = QFrame()
        command_bar.setObjectName("commandBar")
        command_layout = QVBoxLayout(command_bar)
        command_layout.setContentsMargins(14, 10, 14, 9)
        command_layout.setSpacing(7)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        brand = QWidget()
        brand_layout = QVBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 10, 0)
        brand_layout.setSpacing(0)
        brand_title = QLabel("문서 변경점 비교")
        brand_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("기존 문서와 개정 문서를 나란히 확인합니다")
        brand_subtitle.setObjectName("brandSubtitle")
        brand_layout.addWidget(brand_title)
        brand_layout.addWidget(brand_subtitle)

        left_controls = QFrame()
        left_controls.setObjectName("toolbarGroup")
        left_layout = QHBoxLayout(left_controls)
        left_layout.setContentsMargins(8, 5, 8, 5)
        left_layout.setSpacing(7)
        self.compare_button = QPushButton("비교하기")
        self.compare_button.setObjectName("primaryButton")
        self.swap_button = QPushButton("문서 바꾸기")
        self.swap_button.setToolTip("기존 문서와 개정 문서의 위치를 서로 바꿈")
        self.export_button = QPushButton("변경점 출력하기")
        self.export_button.setObjectName("exportButton")
        self.export_button.setToolTip("변경점을 표로 검토한 뒤 Word 보고서로 저장")
        self.export_button.setEnabled(False)
        self.page_mode_button = QPushButton("전체 페이지 보기")
        self.page_mode_button.setEnabled(False)
        self.page_mode_button.setToolTip("전체 페이지와 변경점 페이지만 보기 전환")
        self.page_mode_status = QLabel("현재 보기: 비교 전")
        self.page_mode_status.setObjectName("pageModeStatus")
        self.page_mode_status.setProperty("mode", "idle")
        self.page_mode_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.compare_button)
        left_layout.addWidget(self.swap_button)
        left_layout.addWidget(self.export_button)
        left_layout.addWidget(self.page_mode_button)
        left_layout.addWidget(self.page_mode_status)

        difference_controls = QFrame()
        difference_controls.setObjectName("toolbarGroup")
        difference_layout = QHBoxLayout(difference_controls)
        difference_layout.setContentsMargins(8, 5, 8, 5)
        difference_layout.setSpacing(7)
        self.differences_label = QLabel("변경점")
        self.differences_label.setObjectName("differencesLabel")
        self.differences_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.difference_legend = QLabel(
            '<span style="color:#2f9e5b;">■</span> 추가&nbsp;&nbsp;'
            '<span style="color:#df4f4f;">■</span> 삭제&nbsp;&nbsp;'
            '<span style="color:#d6a900;">■</span> 수정&nbsp;&nbsp;'
            '<span style="color:#1976d2;">▣</span> 파란 테두리: 대응 문단 없음'
        )
        self.difference_legend.setObjectName("differenceLegend")
        self.difference_legend.setToolTip("문서에서 강조된 색상의 의미")
        self.difference_legend.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        difference_layout.addWidget(self.differences_label)
        difference_page_row = QHBoxLayout()
        difference_page_row.setContentsMargins(0, 0, 0, 0)
        difference_page_row.setSpacing(5)
        self.difference_count_label = QLabel("현재")
        self.difference_count_label.setObjectName("differenceCountLabel")
        difference_page_row.addWidget(self.difference_count_label)
        self.difference_page_edit = QLineEdit("0")
        self.difference_page_edit.setObjectName("differencePageEdit")
        self.difference_page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.difference_page_edit.setFixedWidth(48)
        self.difference_page_edit.setMaxLength(6)
        self.difference_page_edit.setToolTip("이동할 변경 문단 번호")
        self.difference_total_label = QLabel("/ 0")
        self.difference_total_label.setObjectName("differenceTotalLabel")
        difference_page_row.addWidget(self.difference_page_edit)
        difference_page_row.addWidget(self.difference_total_label)
        difference_layout.addLayout(difference_page_row)
        difference_buttons = QHBoxLayout()
        difference_buttons.setContentsMargins(0, 0, 0, 0)
        difference_buttons.setSpacing(5)
        self.previous_difference_button = QPushButton("↑")
        self.previous_difference_button.setObjectName("differenceNavigationButton")
        self.previous_difference_button.setToolTip("이전 변경 문단")
        self.previous_difference_button.setAccessibleName("이전 변경 문단")
        self.next_difference_button = QPushButton("↓")
        self.next_difference_button.setObjectName("differenceNavigationButton")
        self.next_difference_button.setToolTip("다음 변경 문단")
        self.next_difference_button.setAccessibleName("다음 변경 문단")
        for button in (self.previous_difference_button, self.next_difference_button):
            button.setFixedSize(34, 30)
            button.setEnabled(False)
        difference_buttons.addWidget(self.previous_difference_button)
        difference_buttons.addWidget(self.next_difference_button)
        difference_layout.addLayout(difference_buttons)

        toolbar.addWidget(brand)
        toolbar.addWidget(left_controls)
        toolbar.addStretch(1)
        toolbar.addWidget(difference_controls)
        command_layout.addLayout(toolbar)
        self.difference_legend.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        command_layout.addWidget(self.difference_legend)
        root.addWidget(command_bar)
        body = QHBoxLayout(); body.setSpacing(0)
        self.old_pane = DocumentPane("OLD")
        self.new_pane = DocumentPane("NEW")
        self.gutter = SyncGutter()
        body.addWidget(self.old_pane, 1); body.addWidget(self.gutter); body.addWidget(self.new_pane, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.loading_overlay = LoadingOverlay(central)
        self.setStatusBar(QStatusBar())
        self.renderer = ComparisonRenderer(self.old_pane, self.new_pane, self.gutter)
        self.renderer.renderingFinished.connect(self._rendering_finished)
        self.renderer.differenceSelected.connect(self._difference_selected)
        self.old_pane.fileSelected.connect(lambda path: self.set_file("old", path))
        self.new_pane.fileSelected.connect(lambda path: self.set_file("new", path))
        self.old_pane.select_button.clicked.connect(lambda: self.select_file("old"))
        self.new_pane.select_button.clicked.connect(lambda: self.select_file("new"))
        self.old_pane.clearRequested.connect(lambda: self.clear_file("old"))
        self.new_pane.clearRequested.connect(lambda: self.clear_file("new"))
        self.swap_button.clicked.connect(self.swap_files)
        self.compare_button.clicked.connect(self.compare_requested)
        self.export_button.clicked.connect(self.open_report_review)
        self.page_mode_button.clicked.connect(self.toggle_page_mode)
        self.previous_difference_button.clicked.connect(self.show_previous_difference)
        self.next_difference_button.clicked.connect(self.show_next_difference)
        self.difference_page_edit.editingFinished.connect(self._difference_page_entered)

    def select_file(self, side: str):
        filename, _ = QFileDialog.getOpenFileName(self, f"Select {side.upper()} document", "", "Documents (*.docx *.pdf)")
        if filename:
            self.set_file(side, Path(filename))

    def open_report_review(self):
        if not (self.old_path and self.new_path and self._report_pairs):
            QMessageBox.information(self, "변경점 출력", "문서 비교를 완료한 뒤 변경점을 출력할 수 있습니다.")
            return
        dialog = ReportReviewDialog(self._report_pairs, self.old_path, self.new_path, self)
        dialog.exec()

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
        self._report_pairs = []
        self.export_button.setEnabled(False)
        self._difference_cursor = -1
        self._set_difference_controls(0, 0, False)
        self.page_mode_button.setText("전체 페이지 보기")
        self.page_mode_button.setEnabled(False)
        self._set_page_mode_status("idle")

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
        self._report_pairs = []
        self.export_button.setEnabled(False)
        self._difference_cursor = -1
        self._set_difference_controls(0, 0, False)
        self.page_mode_button.setText("전체 페이지 보기")
        self.page_mode_button.setEnabled(False)
        self._set_page_mode_status("loading")
        self._set_loading(True)
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
        self._thread.start()

    def _worker_finished(self):
        self._thread = None
        self._worker = None
        if self._pending_compare:
            self._pending_compare = False
            self.compare_if_ready()

    def comparison_ready(self, old: ParsedDocument, new: ParsedDocument, pairs):
        if old.path != self.old_path or new.path != self.new_path:
            return
        self._report_pairs = list(pairs)
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
            self._set_difference_controls(1, target_count, True)
            self.renderer.navigate_difference(0)
        else:
            self._difference_cursor = -1
            self._set_difference_controls(0, 0, False)
        self.page_mode_button.setEnabled(True)
        self.export_button.setEnabled(bool(target_count))
        self.page_mode_button.setText("전체 페이지 보기")
        self._set_page_mode_status("changes")
        self._set_loading(False)
        self.statusBar().showMessage("Comparison complete.", 5000)
        log.info("Comparison complete")

    def comparison_failed(self, old_path: Path, new_path: Path, message: str):
        if old_path != self.old_path or new_path != self.new_path:
            return
        self._set_page_mode_status("failed")
        self._report_pairs = []
        self.export_button.setEnabled(False)
        self._set_loading(False)
        self.statusBar().showMessage("Comparison failed.")
        QMessageBox.critical(self, "Unable to compare documents", message)

    def _set_loading(self, loading: bool):
        self.interactive_content.setEnabled(not loading)
        self.loading_overlay.setVisible(loading)
        if loading:
            self.loading_overlay.spinner.start()
            self.loading_overlay.raise_()
            self.loading_overlay.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.loading_overlay.spinner.stop()

    def _set_difference_controls(self, current: int, total: int, enabled: bool):
        self.difference_page_edit.setText(str(current))
        self.difference_total_label.setText(f"/ {total}")
        self.difference_page_edit.setEnabled(enabled)
        self.previous_difference_button.setEnabled(enabled)
        self.next_difference_button.setEnabled(enabled)

    def _set_page_mode_status(self, mode: str):
        labels = {
            "idle": "현재 보기: 비교 전",
            "loading": "현재 보기: 비교 중",
            "changes": "현재 보기: 변경점 페이지만",
            "all": "현재 보기: 전체 페이지",
            "failed": "현재 보기: 비교 실패",
        }
        self.page_mode_status.setText(labels[mode])
        self.page_mode_status.setProperty("mode", mode)
        self.page_mode_status.style().unpolish(self.page_mode_status)
        self.page_mode_status.style().polish(self.page_mode_status)

    def _difference_page_entered(self):
        targets = self.renderer.difference_targets
        previous = self._difference_cursor + 1 if self._difference_cursor >= 0 else 0
        try:
            requested = int(self.difference_page_edit.text().strip())
        except ValueError:
            requested = 0
        if not 1 <= requested <= len(targets):
            self.difference_page_edit.setText(str(previous))
            return
        self._navigate_difference(requested - 1)

    def _navigate_difference(self, index: int):
        targets = self.renderer.difference_targets
        self._difference_cursor = index % len(targets)
        self.renderer.navigate_difference(self._difference_cursor)
        self.difference_page_edit.setText(str(self._difference_cursor + 1))
        self.difference_total_label.setText(f"/ {len(targets)}")

    def _difference_selected(self, index: int):
        if not 0 <= index < len(self.renderer.difference_targets):
            return
        self._difference_cursor = index
        self.difference_page_edit.setText(str(index + 1))
        self.difference_total_label.setText(f"/ {len(self.renderer.difference_targets)}")

    def _difference_targets_or_warn(self):
        targets = self.renderer.difference_targets
        if not targets:
            QMessageBox.information(self, "변경점", "변경점이 없습니다.")
            return None
        return targets

    def toggle_page_mode(self):
        show_all = not self.renderer.show_all_pages
        self.renderer.set_show_all_pages(show_all)
        self.page_mode_button.setText("변경점 페이지 보기" if show_all else "전체 페이지 보기")
        self._set_page_mode_status("all" if show_all else "changes")
        if not show_all and self._difference_cursor >= 0:
            self.renderer.navigate_difference(self._difference_cursor)

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
            self._pending_compare = False
            self.statusBar().showMessage("Finishing document processing before exit...")
            thread = self._thread
            thread.requestInterruption()
            thread.finished.disconnect(self._worker_finished)
            thread.quit()
            thread.wait()
            self._thread = None
            self._worker = None
            thread.deleteLater()
        self.renderer.cancel_render()
        super().closeEvent(event)
