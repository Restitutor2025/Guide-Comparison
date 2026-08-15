from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QFrame, QScrollBar, QWidget

from guide_comparison.diff.models import AlignedPair, DiffStatus, ParsedDocument, TextBlock
from guide_comparison.diff.text_diff import normalize_text


HIGHLIGHT_COLORS = {
    DiffStatus.ADDED: QColor(79, 207, 126, 105),
    DiffStatus.REMOVED: QColor(255, 104, 104, 100),
    DiffStatus.MODIFIED: QColor(255, 210, 52, 135),
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
            self._dragging = True
            self._last = event.position().toPoint()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            point = event.position().toPoint()
            self.deltaDragged.emit(-(point.y() - self._last.y()))
            self._last = point
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        self.wheelDelta.emit(-event.angleDelta().y())
        event.accept()


@dataclass(frozen=True, slots=True)
class PageHighlight:
    rect: tuple[float, float, float, float]
    status: DiffStatus


@dataclass(frozen=True, slots=True)
class DifferenceTarget:
    old_page: int | None
    new_page: int | None


class PdfPageSource:
    """Lazily render PDF pages and keep a small in-memory pixmap cache."""

    CACHE_LIMIT = 10

    def __init__(self, path: Path):
        self.path = path
        self.document = fitz.open(path)
        self.page_sizes = [
            (float(self.document[index].rect.width), float(self.document[index].rect.height))
            for index in range(len(self.document))
        ]
        self._cache: OrderedDict[tuple[int, int], QPixmap] = OrderedDict()

    def close(self):
        self._cache.clear()
        if self.document:
            self.document.close()
            self.document = None

    def pixmap(self, page_index: int, display_width: int) -> QPixmap:
        key = (page_index, display_width)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        page_width, _ = self.page_sizes[page_index]
        scale = max(0.1, display_width / page_width)
        pixmap = self.document[page_index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = QImage(
            pixmap.samples,
            pixmap.width,
            pixmap.height,
            pixmap.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        rendered = QPixmap.fromImage(image)
        self._cache[key] = rendered
        while len(self._cache) > self.CACHE_LIMIT:
            self._cache.popitem(last=False)
        return rendered

    def search(self, page_number: int, text: str, clip: tuple[float, float, float, float] | None):
        if not self.document or not 1 <= page_number <= len(self.document) or not normalize_text(text):
            return []
        page = self.document[page_number - 1]
        area = fitz.Rect(clip) if clip else None
        return [tuple(float(value) for value in rect) for rect in page.search_for(text.strip(), clip=area)]


class PageCanvas(QWidget):
    """A rendered source page with translucent, selection-like highlights."""

    def __init__(self, source: PdfPageSource, page_index: int, highlights: list[PageHighlight], parent=None):
        super().__init__(parent)
        self.source: PdfPageSource | None = source
        self.page_index = page_index
        self.highlights = highlights
        self.display_width = 500
        self.setProperty("documentPage", True)
        self.setToolTip(f"Page {page_index + 1}")
        self.set_display_width(self.display_width)

    def detach(self):
        self.source = None

    def set_display_width(self, width: int):
        if not self.source:
            return
        width = max(220, int(width))
        page_width, page_height = self.source.page_sizes[self.page_index]
        self.display_width = width
        self.setFixedSize(width, max(1, round(width * page_height / page_width)))
        self.update()

    def paintEvent(self, event):
        if not self.source:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(self.rect(), self.source.pixmap(self.page_index, self.display_width))

        page_width, page_height = self.source.page_sizes[self.page_index]
        x_scale = self.width() / page_width
        y_scale = self.height() / page_height
        painter.setPen(Qt.PenStyle.NoPen)
        for highlight in self.highlights:
            x0, y0, x1, y1 = highlight.rect
            rect = QRectF(
                x0 * x_scale,
                max(0.0, y0 * y_scale - 1.5),
                max(1.0, (x1 - x0) * x_scale),
                max(2.0, (y1 - y0) * y_scale + 3.0),
            )
            painter.fillRect(rect, HIGHLIGHT_COLORS[highlight.status])

        painter.setPen(QPen(QColor("#aeb6c0"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


def _union_rect(rects: list[tuple[float, float, float, float]]):
    if not rects:
        return None
    return (
        min(rect[0] for rect in rects),
        min(rect[1] for rect in rects),
        max(rect[2] for rect in rects),
        max(rect[3] for rect in rects),
    )


def _deduplicate_rects(rects):
    seen = set()
    result = []
    for rect in rects:
        key = tuple(round(value, 2) for value in rect)
        if key not in seen:
            seen.add(key)
            result.append(tuple(float(value) for value in rect))
    return result


class ComparisonRenderer(QObject):
    """Render original pages independently and overlay comparison highlights."""

    renderingFinished = Signal()

    def __init__(self, old_pane, new_pane, gutter: SyncGutter):
        super().__init__(old_pane)
        self.old_pane, self.new_pane, self.gutter = old_pane, new_pane, gutter
        self.old_source: PdfPageSource | None = None
        self.new_source: PdfPageSource | None = None
        self.old_page_widgets: list[PageCanvas] = []
        self.new_page_widgets: list[PageCanvas] = []
        self.old_highlights: dict[int, list[PageHighlight]] = {}
        self.new_highlights: dict[int, list[PageHighlight]] = {}
        self.difference_targets: list[DifferenceTarget] = []
        self._pairs: list[AlignedPair] = []
        self._resize_pending = False

        gutter.deltaDragged.connect(self.scroll_both)
        gutter.wheelDelta.connect(lambda delta: self.scroll_both(int(delta / 2)))
        old_pane.scroll.syncScrollRequested.connect(self.scroll_both)
        new_pane.scroll.syncScrollRequested.connect(self.scroll_both)
        old_pane.scroll.viewport().installEventFilter(self)
        new_pane.scroll.viewport().installEventFilter(self)

    def render(self, old: ParsedDocument, new: ParsedDocument, pairs: list[AlignedPair]):
        self.cancel_render()
        self.old_pane.clear_content()
        self.new_pane.clear_content()
        self._pairs = pairs
        self.difference_targets = self._build_difference_targets(pairs)

        old_path = old.render_path or (old.path if old.path.suffix.lower() == ".pdf" else None)
        new_path = new.render_path or (new.path if new.path.suffix.lower() == ".pdf" else None)
        if not old_path or not new_path:
            raise RuntimeError("Both documents need a rendered PDF view.")

        self.old_source = PdfPageSource(old_path)
        self.new_source = PdfPageSource(new_path)
        self.old_highlights = self._collect_highlights(pairs, True, self.old_source)
        self.new_highlights = self._collect_highlights(pairs, False, self.new_source)
        old_pages = self._target_page_indices(self.difference_targets, True)
        new_pages = self._target_page_indices(self.difference_targets, False)
        self.old_page_widgets = self._populate(self.old_pane, self.old_source, self.old_highlights, old_pages)
        self.new_page_widgets = self._populate(self.new_pane, self.new_source, self.new_highlights, new_pages)
        self._resize_pages()
        for pane in (self.old_pane, self.new_pane):
            pane.content_layout.activate()
            pane.content.adjustSize()
        QTimer.singleShot(0, self.renderingFinished.emit)

    def cancel_render(self):
        for widget in (*self.old_page_widgets, *self.new_page_widgets):
            widget.detach()
        self.old_page_widgets = []
        self.new_page_widgets = []
        if self.old_source:
            self.old_source.close()
        if self.new_source:
            self.new_source.close()
        self.old_source = None
        self.new_source = None
        self.old_highlights = {}
        self.new_highlights = {}
        self.difference_targets = []
        self._pairs = []

    @staticmethod
    def _target_page_indices(targets: list[DifferenceTarget], old_side: bool) -> list[int]:
        """Return changed source pages in navigation order without duplicates."""
        page_numbers = (
            target.old_page if old_side else target.new_page
            for target in targets
        )
        return list(dict.fromkeys(page - 1 for page in page_numbers if page is not None))

    def _populate(self, pane, source: PdfPageSource, highlights, page_indices: list[int]):
        widgets = []
        for page_index in page_indices:
            widget = PageCanvas(source, page_index, highlights.get(page_index, []), pane.content)
            pane.content_layout.insertWidget(
                pane.content_layout.count(),
                widget,
                0,
                Qt.AlignmentFlag.AlignHCenter,
            )
            widgets.append(widget)
        return widgets

    def _collect_highlights(self, pairs: list[AlignedPair], old_side: bool, source: PdfPageSource):
        by_page: dict[int, list[PageHighlight]] = defaultdict(list)
        for pair in pairs:
            if pair.status == DiffStatus.UNCHANGED:
                continue
            block = pair.old_block if old_side else pair.new_block
            if not isinstance(block, TextBlock) or block.page is None or not block.rects:
                continue

            rects = list(block.rects)
            chunks = pair.old_inline if old_side else pair.new_inline
            if pair.status == DiffStatus.MODIFIED and chunks:
                changed_rects = [
                    rect
                    for chunk in chunks
                    if chunk.changed
                    for rect in chunk.rects
                ]
                if not changed_rects:
                    clip = _union_rect(block.rects)
                    for chunk in chunks:
                        if chunk.changed and normalize_text(chunk.text):
                            changed_rects.extend(source.search(block.page, chunk.text, clip))
                if changed_rects:
                    rects = _deduplicate_rects(changed_rects)

            by_page[block.page - 1].extend(PageHighlight(rect, pair.status) for rect in rects)
        return dict(by_page)

    @staticmethod
    def _build_difference_targets(pairs: list[AlignedPair]) -> list[DifferenceTarget]:
        """Build one navigation target per changed source page on either side."""
        all_old_pages = [page for pair in pairs if (page := getattr(pair.old_block, "page", None))]
        all_new_pages = [page for pair in pairs if (page := getattr(pair.new_block, "page", None))]
        max_old_page = max(all_old_pages, default=1)
        max_new_page = max(all_new_pages, default=1)
        changed_old: set[int] = set()
        changed_new: set[int] = set()
        first_old: dict[int, int] = {}
        first_new: dict[int, int] = {}
        for index, pair in enumerate(pairs):
            if pair.status == DiffStatus.UNCHANGED:
                continue
            old_page = getattr(pair.old_block, "page", None)
            new_page = getattr(pair.new_block, "page", None)
            if old_page:
                changed_old.add(old_page)
                first_old.setdefault(old_page, index)
            if new_page:
                changed_new.add(new_page)
                first_new.setdefault(new_page, index)

        page_pair_weights: Counter[tuple[int, int]] = Counter()
        page_pair_first: dict[tuple[int, int], int] = {}
        for index, pair in enumerate(pairs):
            old_page = getattr(pair.old_block, "page", None)
            new_page = getattr(pair.new_block, "page", None)
            if old_page in changed_old and new_page in changed_new:
                key = (old_page, new_page)
                page_pair_weights[key] += 1
                page_pair_first.setdefault(key, index)

        used_old: set[int] = set()
        used_new: set[int] = set()
        targets: list[tuple[int, DifferenceTarget]] = []
        candidates = sorted(
            page_pair_weights,
            key=lambda key: (-page_pair_weights[key], page_pair_first[key]),
        )
        for old_page, new_page in candidates:
            if old_page in used_old or new_page in used_new:
                continue
            used_old.add(old_page)
            used_new.add(new_page)
            targets.append((min(first_old[old_page], first_new[new_page]), DifferenceTarget(old_page, new_page)))

        targets.extend(
            (first_old[page], DifferenceTarget(page, None))
            for page in changed_old - used_old
        )
        targets.extend(
            (first_new[page], DifferenceTarget(None, page))
            for page in changed_new - used_new
        )
        def page_progress(target: DifferenceTarget) -> float:
            positions = []
            if target.old_page:
                positions.append(target.old_page / max_old_page)
            if target.new_page:
                positions.append(target.new_page / max_new_page)
            return min(positions, default=0.0)

        targets.sort(key=lambda item: (page_progress(item[1]), item[0]))
        return [target for _position, target in targets]

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and not self._resize_pending:
            self._resize_pending = True
            QTimer.singleShot(0, self._resize_pages)
        return super().eventFilter(watched, event)

    def _resize_pages(self):
        self._resize_pending = False
        for pane, widgets in (
            (self.old_pane, self.old_page_widgets),
            (self.new_pane, self.new_page_widgets),
        ):
            width = max(220, pane.scroll.viewport().width() - 34)
            for widget in widgets:
                widget.set_display_width(width)

    def scroll_both(self, delta: int):
        for pane in (self.old_pane, self.new_pane):
            bar: QScrollBar = pane.scroll.verticalScrollBar()
            bar.setValue(bar.value() + delta)

    def scroll_to_origin(self):
        for pane in (self.old_pane, self.new_pane):
            pane.scroll.verticalScrollBar().setValue(0)

    def navigate_difference(self, target_index: int):
        if not 0 <= target_index < len(self.difference_targets):
            return
        target = self.difference_targets[target_index]
        targets = (
            (self.old_pane, self.old_page_widgets, target.old_page),
            (self.new_pane, self.new_page_widgets, target.new_page),
        )
        for pane, widgets, page_number in targets:
            page_widget = next(
                (widget for widget in widgets if widget.page_index == page_number - 1),
                None,
            ) if page_number else None
            if page_widget is not None:
                pane.scroll.verticalScrollBar().setValue(max(0, page_widget.y() - 8))
