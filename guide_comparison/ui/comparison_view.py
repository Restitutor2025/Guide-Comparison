from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Signal, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QLabel, QScrollBar, QSizePolicy, QVBoxLayout, QWidget

from guide_comparison.diff.models import AlignedPair, DiffStatus, TableBlock, TextBlock


COLORS = {
    DiffStatus.ADDED: ("#e7f7ec", "#218a42"),
    DiffStatus.REMOVED: ("#fdeaea", "#c2362b"),
    DiffStatus.MODIFIED: ("#fff6d8", "#b37b00"),
    DiffStatus.UNCHANGED: ("#ffffff", "#d7dce2"),
}


class SyncGutter(QFrame):
    deltaDragged = Signal(int)
    wheelDelta = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(20)
        self.setObjectName("syncGutter")
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._dragging = False
        self._last = QPoint()
        self.setToolTip("Drag or wheel here to scroll both documents")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True; self._last = event.position().toPoint(); event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            point = event.position().toPoint()
            self.deltaDragged.emit(-(point.y() - self._last.y()))
            self._last = point; event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False; event.accept()

    def wheelEvent(self, event: QWheelEvent):
        self.wheelDelta.emit(-event.angleDelta().y()); event.accept()


def _inline_html(chunks) -> str:
    return "".join(
        f'<span style="background:#f3c969;font-weight:600">{html.escape(chunk.text)}</span>' if chunk.changed else html.escape(chunk.text)
        for chunk in chunks
    )


def _block_text(block) -> str:
    if isinstance(block, TextBlock):
        return block.text
    if isinstance(block, TableBlock):
        return "\n".join("  |  ".join(row) for row in block.rows)
    return ""


def make_block_widget(pair: AlignedPair, old_side: bool) -> QFrame:
    frame = QFrame()
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    frame.setObjectName("comparisonBlock")
    status = pair.status
    bg, border = COLORS[status]
    frame.setStyleSheet(f"QFrame#comparisonBlock {{background:{bg}; border-left:4px solid {border}; border-radius:4px;}}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 8)
    block = pair.old_block if old_side else pair.new_block
    if block is None:
        label = QLabel("")
        label.setMinimumHeight(18)
    elif isinstance(block, TableBlock) and pair.table_rows:
        rows = []
        for row in pair.table_rows:
            cells = row.old_cells if old_side else row.new_cells
            if cells is None:
                rows.append("&nbsp;")
                continue
            changed = row.changed_old_cells if old_side else row.changed_new_cells
            rendered = [f'<span style="background:#f3c969;font-weight:600">{html.escape(cell)}</span>' if i in changed else html.escape(cell) for i, cell in enumerate(cells)]
            rows.append(" &nbsp;|&nbsp; ".join(rendered))
        label = QLabel("<br>".join(rows))
        label.setTextFormat(Qt.TextFormat.RichText)
    elif status == DiffStatus.MODIFIED and (pair.old_inline if old_side else pair.new_inline):
        label = QLabel(_inline_html(pair.old_inline if old_side else pair.new_inline))
        label.setTextFormat(Qt.TextFormat.RichText)
    else:
        label = QLabel(html.escape(_block_text(block)).replace("\n", "<br>"))
        label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(label)
    if status != DiffStatus.UNCHANGED:
        badge = QLabel(status.value)
        badge.setStyleSheet(f"color:{border}; font-size:10px; font-weight:700; border:none; background:transparent")
        layout.addWidget(badge)
    return frame


class ComparisonRenderer(QObject):
    """Renders both sides in lockstep and keeps corresponding rows equal-height."""

    renderingFinished = Signal()
    BATCH_SIZE = 24
    HEIGHT_BATCH_SIZE = 80

    def __init__(self, old_pane, new_pane, gutter: SyncGutter):
        super().__init__(old_pane)
        self.old_pane, self.new_pane, self.gutter = old_pane, new_pane, gutter
        gutter.deltaDragged.connect(self.scroll_both)
        gutter.wheelDelta.connect(lambda delta: self.scroll_both(int(delta / 2)))
        self.change_positions: list[int] = []
        self._pairs: list[AlignedPair] = []
        self._pair_widgets: list[tuple[QFrame, QFrame]] = []
        self._render_index = 0
        self._generation = 0
        self._height_sync_pending = False
        self._height_sync_token = 0
        self._height_sync_index = 0
        self._rendering = False
        old_pane.scroll.viewport().installEventFilter(self)
        new_pane.scroll.viewport().installEventFilter(self)

    def render(self, pairs: list[AlignedPair]):
        self._generation += 1
        generation = self._generation
        self.old_pane.clear_content(); self.new_pane.clear_content()
        self.change_positions = []
        self._pairs = pairs
        self._pair_widgets = []
        self._render_index = 0
        self._rendering = True
        QTimer.singleShot(0, lambda: self._render_batch(generation))

    def cancel_render(self):
        """Invalidate queued batches so they cannot touch a replaced or closing view."""
        self._generation += 1
        self._height_sync_token += 1
        self._pairs = []
        self._render_index = 0
        self._rendering = False

    def _render_batch(self, generation: int):
        if generation != self._generation:
            return
        end = min(self._render_index + self.BATCH_SIZE, len(self._pairs))
        for index in range(self._render_index, end):
            pair = self._pairs[index]
            old_widget, new_widget = make_block_widget(pair, True), make_block_widget(pair, False)
            self.old_pane.content_layout.insertWidget(self.old_pane.content_layout.count() - 1, old_widget)
            self.new_pane.content_layout.insertWidget(self.new_pane.content_layout.count() - 1, new_widget)
            old_widget.setProperty("pairIndex", index); new_widget.setProperty("pairIndex", index)
            self._pair_widgets.append((old_widget, new_widget))
            if pair.status != DiffStatus.UNCHANGED:
                self.change_positions.append(index)
        self._render_index = end
        if end < len(self._pairs):
            QTimer.singleShot(0, lambda: self._render_batch(generation))
        else:
            QTimer.singleShot(0, lambda: self._start_height_sync(generation, True))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and self._pair_widgets and not self._rendering and not self._height_sync_pending:
            self._height_sync_pending = True
            QTimer.singleShot(0, self._sync_after_resize)
        return super().eventFilter(watched, event)

    def _sync_after_resize(self):
        self._height_sync_pending = False
        if self._pair_widgets:
            self._start_height_sync(self._generation, False)

    def _start_height_sync(self, generation: int, emit_when_done: bool):
        if generation != self._generation:
            return
        self._height_sync_token += 1
        token = self._height_sync_token
        self._height_sync_index = 0
        self._sync_height_batch(generation, token, emit_when_done)

    def _sync_height_batch(self, generation: int, token: int, emit_when_done: bool):
        if generation != self._generation or token != self._height_sync_token:
            return
        end = min(self._height_sync_index + self.HEIGHT_BATCH_SIZE, len(self._pair_widgets))
        self._synchronize_pair_heights(self._pair_widgets[self._height_sync_index:end])
        self._height_sync_index = end
        if end < len(self._pair_widgets):
            QTimer.singleShot(0, lambda: self._sync_height_batch(generation, token, emit_when_done))
        elif emit_when_done:
            self._rendering = False
            self.renderingFinished.emit()

    @staticmethod
    def _natural_height(widget: QFrame) -> int:
        layout = widget.layout()
        width = max(1, widget.contentsRect().width())
        if layout.hasHeightForWidth():
            return max(layout.totalHeightForWidth(width), layout.minimumSize().height())
        return max(layout.sizeHint().height(), layout.minimumSize().height())

    def _synchronize_pair_heights(self, widgets: list[tuple[QFrame, QFrame]]):
        for old_widget, new_widget in widgets:
            old_widget.setMinimumHeight(0); old_widget.setMaximumHeight(16777215)
            new_widget.setMinimumHeight(0); new_widget.setMaximumHeight(16777215)
            old_widget.layout().invalidate(); new_widget.layout().invalidate()
            height = max(self._natural_height(old_widget), self._natural_height(new_widget))
            old_widget.setFixedHeight(height); new_widget.setFixedHeight(height)

    def scroll_both(self, delta: int):
        for pane in (self.old_pane, self.new_pane):
            bar: QScrollBar = pane.scroll.verticalScrollBar()
            bar.setValue(bar.value() + delta)

    def navigate(self, pair_index: int):
        for pane in (self.old_pane, self.new_pane):
            for i in range(pane.content_layout.count()):
                widget = pane.content_layout.itemAt(i).widget()
                if widget and widget.property("pairIndex") == pair_index:
                    pane.scroll.ensureWidgetVisible(widget, 0, 24)
                    break
