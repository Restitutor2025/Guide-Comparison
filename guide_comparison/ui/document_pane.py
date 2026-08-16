from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Signal, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .drop_area import DropArea


class HandScrollArea(QScrollArea):
    """A scroll area with PDF-viewer-style mouse drag panning."""

    syncScrollRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._dragging = False
        self._sync_dragging = False
        self._last = QPoint()
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def _over_document_page(self, point: QPoint) -> bool:
        content = self.widget()
        if content is None:
            return False
        child = content.childAt(content.mapFrom(self.viewport(), point))
        while child is not None and child is not content:
            if child.property("documentPage"):
                return True
            child = child.parentWidget()
        return False

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._sync_dragging = not self._over_document_page(event.position().toPoint())
            self._last = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            point = event.position().toPoint()
            delta = -(point.y() - self._last.y())
            if self._sync_dragging:
                self.syncScrollRequested.emit(delta)
            else:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta)
            self._last = point
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._sync_dragging = False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if not self._over_document_page(event.position().toPoint()):
            self.syncScrollRequested.emit(int(-event.angleDelta().y() / 2))
            event.accept()
            return
        super().wheelEvent(event)


class DocumentPane(QWidget):
    fileSelected = Signal(Path)
    clearRequested = Signal()

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)
        header_frame = QFrame()
        header_frame.setObjectName("paneHeader")
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(10, 7, 8, 7)
        header.setSpacing(7)
        title = QLabel("기존 문서" if role == "OLD" else "비교 문서")
        title.setObjectName("paneTitle")
        role_badge = QLabel(role)
        role_badge.setObjectName("paneRoleBadge")
        role_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info = QLabel("선택된 문서 없음")
        self.info.setObjectName("fileInfo")
        self.select_button = QPushButton("파일 선택")
        self.clear_button = QPushButton("지우기")
        header.addWidget(title)
        header.addWidget(role_badge)
        header.addWidget(self.info, 1)
        header.addWidget(self.select_button)
        header.addWidget(self.clear_button)
        root.addWidget(header_frame)
        self.drop_area = DropArea(role)
        root.addWidget(self.drop_area)
        self.scroll = HandScrollArea()
        self.content = QWidget()
        self.content.setObjectName("pageStack")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        self.drop_area.fileDropped.connect(self.fileSelected)
        self.clear_button.clicked.connect(self.clearRequested)

    def set_document(self, path: Path | None, detail: str = ""):
        self.drop_area.set_file(path)
        self.info.setText(f"{path.name}\n{detail}" if path else "선택된 문서 없음")

    def clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
