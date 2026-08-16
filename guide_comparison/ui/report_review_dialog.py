from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from guide_comparison.reporting import ReportRow, build_report_rows, export_word_report


class ReportReviewDialog(QDialog):
    """Editable report staging area backed by copies of comparison results."""

    HEADERS = ["포함", "번호", "구분", "기존 페이지", "개정 페이지", "기존 내용", "변경 내용", "변경 요약·검토 의견"]

    def __init__(self, pairs, old_path: Path, new_path: Path, parent=None):
        super().__init__(parent)
        self.old_path = Path(old_path)
        self.new_path = Path(new_path)
        self._source_rows = build_report_rows(pairs)
        self.setWindowTitle("변경점 출력 전 검토")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1500, available.width() - 60), min(900, available.height() - 60))
        else:
            self.resize(1400, 850)
        self._build_ui()
        self._populate_table()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(10)

        heading = QLabel("Word 보고서로 저장할 변경점을 검토하세요")
        heading.setObjectName("reportReviewTitle")
        root.addWidget(heading)
        guidance = QLabel(
            "아래 내용은 원본 파일과 분리된 보고용 복사본입니다. 포함 여부와 모든 문구를 직접 수정할 수 있으며, "
            "체크된 행만 새 Word 파일로 저장됩니다."
        )
        guidance.setObjectName("reportReviewGuidance")
        guidance.setWordWrap(True)
        root.addWidget(guidance)

        source_frame = QFrame()
        source_frame.setObjectName("reportSourceBar")
        source_layout = QHBoxLayout(source_frame)
        source_layout.setContentsMargins(10, 7, 10, 7)
        source_layout.addWidget(QLabel(f"기존: {self.old_path.name}"), 1)
        source_layout.addWidget(QLabel(f"개정: {self.new_path.name}"), 1)
        self.selection_status = QLabel()
        self.selection_status.setObjectName("reportSelectionStatus")
        source_layout.addWidget(self.selection_status)
        root.addWidget(source_frame)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("reportReviewTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(88)
        self.table.verticalHeader().setMinimumSectionSize(48)
        header = self.table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._update_selection_status)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        select_all = QPushButton("모두 포함")
        exclude_all = QPushButton("모두 제외")
        select_all.clicked.connect(lambda: self._set_all_included(True))
        exclude_all.clicked.connect(lambda: self._set_all_included(False))
        actions.addWidget(select_all)
        actions.addWidget(exclude_all)
        actions.addStretch(1)
        close_button = QPushButton("닫기")
        export_button = QPushButton("Word로 저장")
        export_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.reject)
        export_button.clicked.connect(self._save_word)
        actions.addWidget(close_button)
        actions.addWidget(export_button)
        root.addLayout(actions)

    @staticmethod
    def _editable_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._source_rows))
        for row_index, row in enumerate(self._source_rows):
            include = QTableWidgetItem()
            include.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            include.setCheckState(Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked)
            include.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_index, 0, include)

            number = QTableWidgetItem(str(row.number))
            number.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            number.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_index, 1, number)

            for column, value in enumerate((
                row.status,
                row.old_page,
                row.new_page,
                row.old_text,
                row.new_text,
                row.review_note,
            ), 2):
                item = self._editable_item(value)
                if column in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column, item)
        self.table.blockSignals(False)
        self._update_selection_status()

    def _set_all_included(self, included: bool):
        state = Qt.CheckState.Checked if included else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(state)
        self._update_selection_status()

    def _update_selection_status(self, *_args):
        included = sum(
            self.table.item(row, 0).checkState() == Qt.CheckState.Checked
            for row in range(self.table.rowCount())
        )
        self.selection_status.setText(f"포함 {included} / 전체 {self.table.rowCount()}")

    def reviewed_rows(self) -> list[ReportRow]:
        rows: list[ReportRow] = []
        for row_index in range(self.table.rowCount()):
            text = lambda column: self.table.item(row_index, column).text().strip()
            rows.append(ReportRow(
                included=self.table.item(row_index, 0).checkState() == Qt.CheckState.Checked,
                number=row_index + 1,
                status=text(2) or "확인 필요",
                old_page=text(3) or "-",
                new_page=text(4) or "-",
                old_text=text(5) or "해당 없음",
                new_text=text(6) or "해당 없음",
                review_note=text(7),
            ))
        return rows

    def _save_word(self):
        if not any(row.included for row in self.reviewed_rows()):
            QMessageBox.warning(self, "변경점 출력", "보고서에 포함할 변경점을 하나 이상 선택하세요.")
            return
        default_name = f"{self.new_path.stem}_변경점_보고서.docx"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Word 변경점 보고서 저장",
            str(self.new_path.parent / default_name),
            "Microsoft Word 문서 (*.docx)",
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".docx":
            destination = destination.with_suffix(".docx")
        source_paths = {self.old_path.resolve(), self.new_path.resolve()}
        if destination.resolve() in source_paths:
            QMessageBox.warning(
                self,
                "원본 파일 보호",
                "원본 문서와 같은 경로에는 저장할 수 없습니다. 새 파일명을 선택하세요.",
            )
            return
        try:
            export_word_report(
                destination,
                self.reviewed_rows(),
                self.old_path.name,
                self.new_path.name,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Word 저장 실패", str(exc))
            return
        QMessageBox.information(self, "변경점 출력 완료", f"Word 보고서를 저장했습니다.\n\n{destination}")
