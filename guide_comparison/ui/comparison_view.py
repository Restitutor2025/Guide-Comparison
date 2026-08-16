from __future__ import annotations

from collections import OrderedDict, defaultdict
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
    pair_index: int
    old_page: int
    new_page: int
    old_rect: tuple[float, float, float, float] | None
    new_rect: tuple[float, float, float, float] | None
    status: DiffStatus
    has_counterpart: bool


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

    def __init__(
        self,
        source: PdfPageSource,
        page_index: int,
        highlights: list[PageHighlight],
        target_rects: dict[int, tuple[float, float, float, float]] | None = None,
        unpaired_targets: set[int] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.source: PdfPageSource | None = source
        self.page_index = page_index
        self.highlights = highlights
        self.target_rects = target_rects or {}
        self.unpaired_targets = unpaired_targets or set()
        self.focus_target: int | None = None
        self.display_width = 500
        self.setProperty("documentPage", True)
        self.setToolTip(f"Page {page_index + 1} · 변경 문단을 클릭하면 양쪽 위치를 맞춥니다")
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

    def set_focus_target(self, target_index: int | None):
        if self.focus_target != target_index:
            self.focus_target = target_index
            self.update()

    def target_at(self, point: QPoint) -> int | None:
        if not self.source:
            return None
        page_width, page_height = self.source.page_sizes[self.page_index]
        x = point.x() * page_width / max(1, self.width())
        y = point.y() * page_height / max(1, self.height())
        matches = []
        for target_index, rect in self.target_rects.items():
            x0, y0, x1, y1 = rect
            margin = max(3.0, (y1 - y0) * 0.18)
            if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin:
                matches.append(((x1 - x0) * (y1 - y0), target_index))
        return min(matches)[1] if matches else None

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

        focus_rect = self.target_rects.get(self.focus_target)
        if focus_rect is not None:
            x0, y0, x1, y1 = focus_rect
            rect = QRectF(
                x0 * x_scale,
                y0 * y_scale,
                max(1.0, (x1 - x0) * x_scale),
                max(2.0, (y1 - y0) * y_scale),
            ).adjusted(-3, -3, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            outline_color = "#1976d2" if self.focus_target in self.unpaired_targets else "#d62828"
            painter.setPen(QPen(QColor(outline_color), 3))
            painter.drawRect(rect)

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
    differenceSelected = Signal(int)

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
        self._changed_page_pairs: list[tuple[int, int]] = []
        self._pairs: list[AlignedPair] = []
        self._old_document: ParsedDocument | None = None
        self._new_document: ParsedDocument | None = None
        self.show_all_pages = False
        self._resize_pending = False
        self._active_target: int | None = None
        self._hovered_target: int | None = None
        self._pressed_target: int | None = None
        self._press_point = QPoint()
        self._press_dragged = False

        gutter.deltaDragged.connect(self.scroll_both)
        gutter.wheelDelta.connect(lambda delta: self.scroll_both(int(delta / 2)))
        old_pane.scroll.syncScrollRequested.connect(self.scroll_both)
        new_pane.scroll.syncScrollRequested.connect(self.scroll_both)
        self._old_viewport = old_pane.scroll.viewport()
        self._new_viewport = new_pane.scroll.viewport()
        self._old_viewport.setMouseTracking(True)
        self._new_viewport.setMouseTracking(True)
        self._old_viewport.installEventFilter(self)
        self._new_viewport.installEventFilter(self)

    def render(self, old: ParsedDocument, new: ParsedDocument, pairs: list[AlignedPair]):
        self.cancel_render()
        self.old_pane.clear_content()
        self.new_pane.clear_content()
        self._pairs = pairs
        self._old_document, self._new_document = old, new
        self.show_all_pages = False
        self.difference_targets = self._build_difference_targets(pairs, old.page_count, new.page_count)
        self._changed_page_pairs = list(dict.fromkeys(
            (target.old_page, target.new_page) for target in self.difference_targets
        ))

        old_path = old.render_path or (old.path if old.path.suffix.lower() == ".pdf" else None)
        new_path = new.render_path or (new.path if new.path.suffix.lower() == ".pdf" else None)
        if not old_path or not new_path:
            raise RuntimeError("Both documents need a rendered PDF view.")

        self.old_source = PdfPageSource(old_path)
        self.new_source = PdfPageSource(new_path)
        self.old_highlights = self._collect_highlights(pairs, True, self.old_source)
        self.new_highlights = self._collect_highlights(pairs, False, self.new_source)
        self._render_page_stacks()
        QTimer.singleShot(0, self.renderingFinished.emit)

    def _render_page_stacks(self):
        if not self.old_source or not self.new_source:
            return
        for widget in (*self.old_page_widgets, *self.new_page_widgets):
            widget.detach()
        self.old_page_widgets = []
        self.new_page_widgets = []
        self.old_pane.clear_content()
        self.new_pane.clear_content()
        if self.show_all_pages:
            old_pages = list(range(len(self.old_source.page_sizes)))
            new_pages = list(range(len(self.new_source.page_sizes)))
        else:
            # Keep the stacks index-aligned: every changed page always has a
            # real counterpart page on the other side.
            old_pages = [old_page - 1 for old_page, _new_page in self._changed_page_pairs]
            new_pages = [new_page - 1 for _old_page, new_page in self._changed_page_pairs]
        self.old_page_widgets = self._populate(self.old_pane, self.old_source, self.old_highlights, old_pages, True)
        self.new_page_widgets = self._populate(self.new_pane, self.new_source, self.new_highlights, new_pages, False)
        self._resize_pages()
        for pane in (self.old_pane, self.new_pane):
            pane.content_layout.activate()
            pane.content.adjustSize()

    def set_show_all_pages(self, show_all: bool):
        if self.show_all_pages == show_all or not self.old_source or not self.new_source:
            return
        self.show_all_pages = show_all
        self._render_page_stacks()
        self.scroll_to_origin()

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
        self._changed_page_pairs = []
        self._pairs = []
        self._old_document = None
        self._new_document = None
        self.show_all_pages = False
        self._active_target = None
        self._hovered_target = None

    @staticmethod
    def _target_page_indices(targets: list[DifferenceTarget], old_side: bool) -> list[int]:
        """Return changed source pages in navigation order without duplicates."""
        page_numbers = (
            target.old_page if old_side else target.new_page
            for target in targets
        )
        return list(dict.fromkeys(page - 1 for page in page_numbers if page is not None))

    def _populate(self, pane, source: PdfPageSource, highlights, page_indices: list[int], old_side: bool):
        widgets = []
        for page_index in page_indices:
            target_rects = {
                target_index: rect
                for target_index, target in enumerate(self.difference_targets)
                if (target.old_page if old_side else target.new_page) == page_index + 1
                and (rect := (target.old_rect if old_side else target.new_rect)) is not None
            }
            unpaired_targets = {
                target_index
                for target_index, target in enumerate(self.difference_targets)
                if not target.has_counterpart and target_index in target_rects
            }
            widget = PageCanvas(
                source,
                page_index,
                highlights.get(page_index, []),
                target_rects,
                unpaired_targets,
                pane.content,
            )
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
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
                inline_highlights: list[PageHighlight] = []
                clip = _union_rect(block.rects)
                for chunk in chunks:
                    if not chunk.changed:
                        continue
                    chunk_rects = list(chunk.rects)
                    if not chunk_rects and normalize_text(chunk.text):
                        chunk_rects.extend(source.search(block.page, chunk.text, clip))
                    status = chunk.status if chunk.status != DiffStatus.UNCHANGED else DiffStatus.MODIFIED
                    inline_highlights.extend(
                        PageHighlight(rect, status) for rect in _deduplicate_rects(chunk_rects)
                    )
                if inline_highlights:
                    by_page[block.page - 1].extend(inline_highlights)
                    continue

            by_page[block.page - 1].extend(PageHighlight(rect, pair.status) for rect in rects)
        return dict(by_page)

    @staticmethod
    def _build_difference_targets(
        pairs: list[AlignedPair],
        old_page_count: int | None = None,
        new_page_count: int | None = None,
    ) -> list[DifferenceTarget]:
        """Build one navigation target per changed paragraph, with paired pages."""
        all_old_pages = [page for pair in pairs if (page := getattr(pair.old_block, "page", None))]
        all_new_pages = [page for pair in pairs if (page := getattr(pair.new_block, "page", None))]
        max_old_page = max(1, old_page_count or max(all_old_pages, default=1))
        max_new_page = max(1, new_page_count or max(all_new_pages, default=1))
        page_anchors = [
            (index, old_page, new_page)
            for index, pair in enumerate(pairs)
            if (old_page := getattr(pair.old_block, "page", None))
            and (new_page := getattr(pair.new_block, "page", None))
        ]

        def counterpart(page: int, old_to_new: bool, pair_index: int) -> int:
            source_max, target_max = (max_old_page, max_new_page) if old_to_new else (max_new_page, max_old_page)
            candidates = []
            for anchor_index, old_page, new_page in page_anchors:
                source_page, target_page = (old_page, new_page) if old_to_new else (new_page, old_page)
                candidates.append((abs(source_page - page), abs(anchor_index - pair_index), source_page, target_page))
            if candidates:
                _page_distance, _index_distance, source_page, target_page = min(candidates)
                return max(1, min(target_max, target_page + page - source_page))
            proportional = round(page * target_max / source_max)
            return max(1, min(target_max, proportional))

        targets: list[DifferenceTarget] = []
        for index, pair in enumerate(pairs):
            if pair.status == DiffStatus.UNCHANGED:
                continue
            old_page = getattr(pair.old_block, "page", None)
            new_page = getattr(pair.new_block, "page", None)
            if old_page is None and new_page is None:
                continue
            if old_page is None:
                old_page = counterpart(new_page, False, index)
            if new_page is None:
                new_page = counterpart(old_page, True, index)
            old_rect = _union_rect(pair.old_block.rects) if isinstance(pair.old_block, TextBlock) else None
            new_rect = _union_rect(pair.new_block.rects) if isinstance(pair.new_block, TextBlock) else None
            targets.append(DifferenceTarget(
                index,
                old_page,
                new_page,
                old_rect,
                new_rect,
                pair.status,
                pair.old_block is not None and pair.new_block is not None,
            ))
        return targets

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and not self._resize_pending:
            self._resize_pending = True
            QTimer.singleShot(0, self._resize_pages)
        interactive_surface = (
            watched is self._old_viewport
            or watched is self._new_viewport
            or isinstance(watched, PageCanvas)
        )
        if interactive_surface:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._press_point = event.globalPosition().toPoint()
                self._pressed_target = self._target_at_global(self._press_point)
                self._press_dragged = False
            elif event.type() == QEvent.Type.MouseMove:
                point = event.globalPosition().toPoint()
                if event.buttons() and (point - self._press_point).manhattanLength() > 6:
                    self._press_dragged = True
                if not event.buttons():
                    self._set_hovered_target(self._target_at_global(point))
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                target_index = self._target_at_global(event.globalPosition().toPoint())
                should_select = not self._press_dragged and target_index is not None and target_index == self._pressed_target
                self._pressed_target = None
                self._press_dragged = False
                if should_select:
                    self.navigate_difference(target_index)
                    self.differenceSelected.emit(target_index)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self._set_hovered_target(None)
        return super().eventFilter(watched, event)

    def _target_at_global(self, global_point: QPoint) -> int | None:
        for widget in (*self.old_page_widgets, *self.new_page_widgets):
            local_point = widget.mapFromGlobal(global_point)
            if widget.rect().contains(local_point):
                return widget.target_at(local_point)
        return None

    def _set_hovered_target(self, target_index: int | None):
        if self._hovered_target == target_index:
            return
        self._hovered_target = target_index
        self._update_target_outlines(target_index if target_index is not None else self._active_target)

    def _update_target_outlines(self, target_index: int | None):
        for widget in (*self.old_page_widgets, *self.new_page_widgets):
            widget.set_focus_target(target_index)

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
        self._active_target = target_index
        self._update_target_outlines(self._hovered_target if self._hovered_target is not None else target_index)
        target = self.difference_targets[target_index]
        targets = (
            (self.old_pane, self.old_page_widgets, target.old_page, target.old_rect),
            (self.new_pane, self.new_page_widgets, target.new_page, target.new_rect),
        )
        page_pair = (target.old_page, target.new_page)
        changed_page_index = self._changed_page_pairs.index(page_pair) if page_pair in self._changed_page_pairs else -1
        for pane, widgets, page_number, paragraph_rect in targets:
            if self.show_all_pages:
                page_widget = next((widget for widget in widgets if widget.page_index == page_number - 1), None)
            else:
                page_widget = widgets[changed_page_index] if 0 <= changed_page_index < len(widgets) else None
            if page_widget is not None:
                if not target.has_counterpart and paragraph_rect is None:
                    continue
                paragraph_y = 0.0
                if paragraph_rect is not None and page_widget.source:
                    page_height = page_widget.source.page_sizes[page_widget.page_index][1]
                    paragraph_y = paragraph_rect[1] * page_widget.height() / page_height
                desired_y = page_widget.y() + paragraph_y - pane.scroll.viewport().height() * 0.28
                pane.scroll.verticalScrollBar().setValue(max(0, round(desired_y)))
