from __future__ import annotations

import re
from contextlib import redirect_stdout
from collections import Counter
from io import StringIO
from pathlib import Path

import pymupdf as fitz

from guide_comparison.diff.models import ParsedDocument, TextBlock
from guide_comparison.parsers.base import DocumentParseError


_PAGE_NUMBER = re.compile(r"^\s*(?:[-–—]\s*)?\d+(?:\s*[-–—])?\s*$")
_BULLET = re.compile(r"^\s*(?:[•●▪◦*-]|\d+[.)])\s+")
_DATE_ONLY = re.compile(r"^\s*(?:19|20)\d{2}\s*(?:[.\-/년]\s*\d{1,2})?(?:\s*[.\-/월]\s*\d{1,2}\s*일?)?\.?\s*$")
_STRUCTURAL_START = re.compile(r"^\s*(?:[•●▪◦*\-○□■※☎☞]|\d+[.)]\s+|[가-하][.)]\s+|제\s*\d+\s*[조장절])")
_TERMINAL_END = re.compile(r"[.!?。！？:;：；]\s*[\"'”’）)\]]*\s*$")


def _normalize_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        if result.endswith(("-", "‐")) and line[:1].islower():
            result = result[:-1] + line
        else:
            result += " " + line
    return result.strip()


def _type_for(text: str, size: float, median_size: float) -> str:
    if _BULLET.match(text):
        return "list"
    if size >= median_size * 1.18 and len(text) < 180:
        return "heading"
    return "paragraph"


def _inside_table(rects, table_boxes) -> bool:
    for rect in rects:
        center_x = (rect[0] + rect[2]) / 2
        center_y = (rect[1] + rect[3]) / 2
        if any(box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3] for box in table_boxes):
            return True
    return False


def _should_merge(previous: TextBlock, current: TextBlock, page_width: float, table_boxes) -> bool:
    if previous.block_type != "paragraph" or current.block_type != "paragraph":
        return False
    if not previous.rects or not current.rects:
        return False
    if _inside_table(previous.rects, table_boxes) or _inside_table(current.rects, table_boxes):
        return False
    if _TERMINAL_END.search(previous.text) or _STRUCTURAL_START.match(current.text) or _DATE_ONLY.match(current.text):
        return False

    previous_line = previous.rects[-1]
    current_line = current.rects[0]
    line_height = max(previous_line[3] - previous_line[1], current_line[3] - current_line[1], 1.0)
    vertical_gap = current_line[1] - previous_line[3]
    if not -1.0 <= vertical_gap <= line_height * 1.25:
        return False
    if abs(current_line[0] - previous_line[0]) > line_height * 2.1:
        return False

    previous_width = previous_line[2] - previous_line[0]
    return previous_width >= page_width * 0.45 or len(previous.text) >= 28


def _merge_page_blocks(blocks: list[TextBlock], page_width: float, table_boxes) -> list[TextBlock]:
    merged: list[TextBlock] = []
    for block in blocks:
        if merged and _should_merge(merged[-1], block, page_width, table_boxes):
            previous = merged[-1]
            previous.text = f"{previous.text} {block.text}"
            previous.rects.extend(block.rects)
            previous.chars.extend(block.chars)
        else:
            merged.append(block)
    return merged


def parse_pdf(path: Path, *, source_path: Path | None = None) -> ParsedDocument:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise DocumentParseError(f"This PDF file is invalid or corrupted.\n\nDetails: {exc}") from exc
    try:
        if document.needs_pass:
            raise DocumentParseError("This PDF is encrypted. Password-protected PDFs are not supported.")
        page_items: list[list[tuple[str, float, float, list[tuple[float, float, float, float]], list[tuple[str, float, float, float, float]]]]] = []
        page_table_boxes: list[list[tuple[float, float, float, float]]] = []
        page_widths: list[float] = []
        edge_candidates: list[str] = []
        sizes: list[float] = []
        for page in document:
            entries = []
            data = page.get_text("rawdict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = []
                block_sizes = []
                line_rects: list[tuple[float, float, float, float]] = []
                block_chars: list[tuple[str, float, float, float, float]] = []
                for line in block.get("lines", []):
                    text_parts = []
                    for span in line.get("spans", []):
                        span_chars = span.get("chars", [])
                        text_parts.append("".join(char.get("c", "") for char in span_chars))
                        for char in span_chars:
                            bbox = char.get("bbox")
                            value = char.get("c", "")
                            if value and bbox and len(bbox) == 4:
                                block_chars.append((value, *(float(item) for item in bbox)))
                    text = "".join(text_parts)
                    if text.strip():
                        lines.append(text)
                        block_sizes.extend(float(span.get("size", 10)) for span in line.get("spans", []))
                        bbox = line.get("bbox")
                        if bbox and len(bbox) == 4:
                            line_rects.append(tuple(float(value) for value in bbox))
                text = _normalize_lines("\n".join(lines))
                if not text or _PAGE_NUMBER.match(text):
                    continue
                y = float(block.get("bbox", (0, 0, 0, 0))[1])
                size = sum(block_sizes) / len(block_sizes) if block_sizes else 10.0
                entries.append((text, y, size, line_rects, block_chars)); sizes.append(size)
                if y < page.rect.height * 0.12 or y > page.rect.height * 0.88:
                    edge_candidates.append(text)
            page_items.append(entries)
            page_widths.append(float(page.rect.width))
            try:
                drawing_item_count = sum(len(drawing.get("items", [])) for drawing in page.get_drawings())
                if len(entries) >= 12 and drawing_item_count >= 30:
                    with redirect_stdout(StringIO()):
                        tables = page.find_tables().tables
                    page_table_boxes.append([
                        tuple(float(value) for value in table.bbox)
                        for table in tables
                    ])
                else:
                    page_table_boxes.append([])
            except Exception:
                page_table_boxes.append([])
        repeated = {text for text, count in Counter(edge_candidates).items() if count >= max(2, len(document) // 2)}
        median = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
        blocks = []
        for page_index, entries in enumerate(page_items):
            page_blocks = [
                TextBlock(text, _type_for(text, size, median), page_index + 1, rects, chars)
                for text, _y, size, rects, chars in entries
                if text not in repeated
            ]
            blocks.extend(_merge_page_blocks(
                page_blocks,
                page_widths[page_index],
                page_table_boxes[page_index],
            ))
        warning = None
        extracted = sum(len(block.text) for block in blocks)
        if len(document) and extracted < max(20, len(document) * 8):
            warning = "This PDF appears to contain little or no extractable text.\n\nScanned PDF OCR is not supported in this version."
        return ParsedDocument(source_path or path, blocks, len(document), warning, path)
    finally:
        document.close()
