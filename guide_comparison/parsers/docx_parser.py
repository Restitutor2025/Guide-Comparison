from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from guide_comparison.diff.models import ParsedDocument, TableBlock, TextBlock
from guide_comparison.parsers.base import DocumentParseError


def _iter_children(parent: DocumentObject | _Cell):
    parent_element = parent.element.body if isinstance(parent, DocumentObject) else parent._tc
    for child in parent_element.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def _paragraph_type(paragraph: Paragraph) -> str:
    style = (paragraph.style.name if paragraph.style else "").lower()
    if style.startswith("heading") or style.startswith("title"):
        return "heading"
    p_pr = paragraph._p.pPr
    if "list" in style or (p_pr is not None and p_pr.numPr is not None):
        return "list"
    return "paragraph"


def _cell_text(cell: _Cell) -> str:
    return "\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip())


def parse_docx(path: Path) -> ParsedDocument:
    try:
        document = Document(path)
    except Exception as exc:
        raise DocumentParseError(f"This DOCX file is invalid or corrupted.\n\nDetails: {exc}") from exc
    blocks = []
    for item in _iter_children(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                blocks.append(TextBlock(text, _paragraph_type(item)))
        else:
            rows = [[_cell_text(cell) for cell in row.cells] for row in item.rows]
            if rows:
                blocks.append(TableBlock(rows))
    return ParsedDocument(path, blocks)

