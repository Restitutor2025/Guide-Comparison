from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Signal, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .drop_area import DropArea


class HandScrollArea(QScrollArea):
    """A scroll area with PDF-viewer-style mouse drag panning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._dragging = False
        self._last = QPoint()
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            point = event.position().toPoint()
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - (point.y() - self._last.y()))
            self._last = point
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DocumentPane(QWidget):
    fileSelected = Signal(Path)
    clearRequested = Signal()

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title = QLabel(role)
        title.setObjectName("paneTitle")
        self.info = QLabel("No document")
        self.info.setObjectName("fileInfo")
        self.select_button = QPushButton(f"Select {role.title()} File")
        self.clear_button = QPushButton("Clear")
        header.addWidget(title)
        header.addWidget(self.info, 1)
        header.addWidget(self.select_button)
        header.addWidget(self.clear_button)
        root.addLayout(header)
        self.drop_area = DropArea(role)
        root.addWidget(self.drop_area)
        self.scroll = HandScrollArea()
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(8)
        self.content_layout.addStretch(1)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        self.drop_area.fileDropped.connect(self.fileSelected)
        self.clear_button.clicked.connect(self.clearRequested)

    def set_document(self, path: Path | None, detail: str = ""):
        self.drop_area.set_file(path)
        self.info.setText(f"{path.name}\n{detail}" if path else "No document")

    def clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.content_layout.addStretch(1)

