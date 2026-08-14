from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from guide_comparison.diff.models import ParsedDocument, TextBlock
from guide_comparison.parsers.base import DocumentParseError


_PAGE_NUMBER = re.compile(r"^\s*(?:[-–—]\s*)?\d+(?:\s*[-–—])?\s*$")
_BULLET = re.compile(r"^\s*(?:[•●▪◦*-]|\d+[.)])\s+")


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


def parse_pdf(path: Path) -> ParsedDocument:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise DocumentParseError(f"This PDF file is invalid or corrupted.\n\nDetails: {exc}") from exc
    try:
        if document.needs_pass:
            raise DocumentParseError("This PDF is encrypted. Password-protected PDFs are not supported.")
        page_items: list[list[tuple[str, float, float]]] = []
        edge_candidates: list[str] = []
        sizes: list[float] = []
        for page in document:
            entries = []
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = []
                block_sizes = []
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", []))
                    if text.strip():
                        lines.append(text)
                        block_sizes.extend(float(span.get("size", 10)) for span in line.get("spans", []))
                text = _normalize_lines("\n".join(lines))
                if not text or _PAGE_NUMBER.match(text):
                    continue
                y = float(block.get("bbox", (0, 0, 0, 0))[1])
                size = sum(block_sizes) / len(block_sizes) if block_sizes else 10.0
                entries.append((text, y, size)); sizes.append(size)
                if y < page.rect.height * 0.12 or y > page.rect.height * 0.88:
                    edge_candidates.append(text)
            page_items.append(entries)
        repeated = {text for text, count in Counter(edge_candidates).items() if count >= max(2, len(document) // 2)}
        median = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
        blocks = [TextBlock(text, _type_for(text, size, median), page_no) for page_no, entries in enumerate(page_items, 1) for text, _y, size in entries if text not in repeated]
        warning = None
        extracted = sum(len(block.text) for block in blocks)
        if len(document) and extracted < max(20, len(document) * 8):
            warning = "This PDF appears to contain little or no extractable text.\n\nScanned PDF OCR is not supported in this version."
        return ParsedDocument(path, blocks, len(document), warning)
    finally:
        document.close()
