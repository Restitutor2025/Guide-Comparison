from __future__ import annotations

from pathlib import Path

from guide_comparison.diff.models import ParsedDocument


class DocumentParseError(RuntimeError):
    pass


def validate_path(path: Path) -> None:
    if path.suffix.lower() not in {".docx", ".pdf"}:
        raise DocumentParseError("Unsupported file type.\n\nSupported:\nDOCX\nPDF")
    if not path.exists():
        raise DocumentParseError("The selected file no longer exists.")
    if not path.is_file():
        raise DocumentParseError("The selected path is not a file.")


def parse_document(path: str | Path) -> ParsedDocument:
    path = Path(path)
    validate_path(path)
    try:
        if path.suffix.lower() == ".docx":
            from .docx_parser import parse_docx

            return parse_docx(path)
        from .pdf_parser import parse_pdf

        return parse_pdf(path)
    except DocumentParseError:
        raise
    except PermissionError as exc:
        raise DocumentParseError(f"Permission denied while reading:\n{path}") from exc
    except Exception as exc:
        raise DocumentParseError(f"Unable to read {path.name}.\n\nDetails: {exc}") from exc

