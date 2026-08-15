# Guide Comparison

Guide Comparison is a local, deterministic desktop application for comparing an older work guide with a newer revision. It renders the original pages and overlays text changes without AI, cloud services, or modifying the source files.

## Features

- OLD/NEW drag and drop plus file-picker fallback
- Original PDF/Word page layout instead of reconstructed text cards
- Selection-like overlays: added (green), removed (red), and modified (yellow)
- No virtual blank pages or placeholder cards for one-sided content
- Lazy page rendering to keep long documents responsive
- Independent hand-drag and wheel scrolling directly over either document page
- Synchronized drag and wheel scrolling from page margins or the center gutter
- Page-level `Differences` navigation, swap, clear, and file replacement
- Background parsing and comparison so the interface stays responsive
- Read-only processing: input documents are never changed

## Supported formats

- PDF via `PyMuPDF`
- DOCX rendered to PDF via LibreOffice, then processed with the same page pipeline

Text extraction uses positional blocks so highlights can be drawn over their original page coordinates. LibreOffice is required for DOCX page rendering; its output is very close to Word but is not guaranteed to be pixel-identical to Microsoft Word.

## Installation and run

```bash
git clone https://github.com/Restitutor2025/Guide-Comparison.git
cd Guide-Comparison
python run.py
```

On the first launch, `run.py` creates a project-local `.venv`, restarts itself with that environment's Python interpreter, and installs missing dependencies from `requirements.txt`. Later launches reuse the same isolated environment automatically.

## Usage

1. Drop the previous `.docx` or `.pdf` into OLD, or select it with **Select Old File**.
2. Drop the latest document into NEW, or select it with **Select New File**.
3. Comparison starts automatically once both documents are present.
4. Drop a replacement on either side to compare again automatically.

Use **Swap OLD ↔ NEW** if the versions were reversed. **Clear** removes a document from the comparison but never deletes or alters the source file.

## Highlight meaning

- Green: content exists only in NEW.
- Red: content exists only in OLD.
- Yellow: corresponding content exists on both sides but changed.
- No highlight: normalized comparison text is equal.

## Scrolling controls

- Drag or wheel directly over an OLD page to move only OLD.
- Drag or wheel directly over a NEW page to move only NEW.
- Drag or wheel over the gray page margins or center gutter to move both sides.
- Each **Differences** click moves to the next changed page from top to bottom.
- Multiple highlights on the same page count as one difference target.
- After the last changed page, the next click returns to the top and opens the first target again.

## Tests

Run the standard-library test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover insertion/deletion realignment, layout-only text normalization, Korean numeric edits, inline differences, table row/cell changes, DOCX rendering, PDF extraction and coordinates, original-page overlays, synchronized margin dragging, unsupported files, and corrupt documents.

## Known limitations

- OCR and scanned-PDF recognition are not supported; a warning is shown when little extractable text is found.
- Image, diagram, drawing, and other non-text visual differences are not compared.
- PDF and rendered DOCX table structures are treated as positional text in this version.
- LibreOffice-rendered DOCX layout can differ slightly from Microsoft Word because the layout engines are different.
- Semantic paraphrases are not automatically treated as identical; doing so could hide small but legally meaningful changes such as numbers, obligations, and exceptions.
- Page images are rendered lazily with a bounded cache, but extremely large documents can still require noticeable processing time.
- Password-protected PDFs are rejected.
