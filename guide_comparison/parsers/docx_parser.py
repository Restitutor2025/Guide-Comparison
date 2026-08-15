from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from guide_comparison.diff.models import ParsedDocument, TableBlock, TextBlock
from guide_comparison.parsers.base import DocumentParseError
from guide_comparison.parsers.pdf_parser import parse_pdf


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


def _extract_docx_blocks(path: Path) -> list[TextBlock | TableBlock]:
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
    return blocks


def _find_soffice() -> str | None:
    configured = os.environ.get("GUIDE_COMPARISON_SOFFICE")
    candidates = (
        configured,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    )
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def _render_docx_to_pdf(path: Path) -> Path:
    soffice = _find_soffice()
    if not soffice:
        raise DocumentParseError(
            "Word page rendering requires LibreOffice.\n\n"
            "Install LibreOffice or set GUIDE_COMPARISON_SOFFICE to its executable path."
        )

    stat = path.stat()
    fingerprint = hashlib.sha256(
        f"{path.resolve()}\0{stat.st_mtime_ns}\0{stat.st_size}".encode("utf-8")
    ).hexdigest()[:20]
    cache_dir = Path(tempfile.gettempdir()) / "guide-comparison-docx-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_pdf = cache_dir / f"{fingerprint}.pdf"
    if cached_pdf.is_file() and cached_pdf.stat().st_size:
        return cached_pdf

    with tempfile.TemporaryDirectory(prefix="guide-comparison-lo-") as temp_folder:
        temp_dir = Path(temp_folder)
        output_dir = temp_dir / "output"
        profile_dir = temp_dir / "profile"
        output_dir.mkdir()
        profile_dir.mkdir()
        completed = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(output_dir),
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        rendered = output_dir / f"{path.stem}.pdf"
        if not rendered.is_file():
            candidates = list(output_dir.glob("*.pdf"))
            rendered = candidates[0] if len(candidates) == 1 else rendered
        if completed.returncode or not rendered.is_file() or not rendered.stat().st_size:
            details = (completed.stderr or completed.stdout or "Unknown LibreOffice conversion error").strip()
            raise DocumentParseError(f"Unable to render this DOCX for page comparison.\n\nDetails: {details}")
        shutil.move(str(rendered), cached_pdf)
    return cached_pdf


def parse_docx(path: Path) -> ParsedDocument:
    # Validate the OOXML package first so corrupt files keep a DOCX-specific error.
    _extract_docx_blocks(path)
    rendered_pdf = _render_docx_to_pdf(path)
    return parse_pdf(rendered_pdf, source_path=path)
