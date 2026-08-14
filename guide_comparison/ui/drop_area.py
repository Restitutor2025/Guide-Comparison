from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


class DropArea(QFrame):
    fileDropped = Signal(Path)

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setMinimumHeight(80)
        layout = QVBoxLayout(self)
        self.label = QLabel(f"Drag {role.lower()} document here")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.fileDropped.emit(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def set_file(self, path: Path | None):
        self.label.setText(path.name if path else f"Drag {self.role.lower()} document here")

