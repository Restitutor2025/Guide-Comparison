# Guide Comparison

Guide Comparison is a local, deterministic desktop application for comparing an older work guide with a newer revision. It highlights actual paragraph, character, table-row, and table-cell changes without AI, cloud services, or modifying the source files.

## Features

- OLD/NEW drag and drop plus file-picker fallback
- Side-by-side aligned blocks with virtual blank space for additions and removals
- Added (green), removed (red), modified (yellow), and unchanged states with text labels
- Inline word/character highlighting for modified text
- Row-aligned table comparison with changed-cell highlighting
- Independent hand-drag and wheel scrolling in each document
- Center-gutter hand-drag and wheel scrolling for synchronized delta movement
- Previous/next change navigation, summary counts, swap, clear, and file replacement
- Background parsing and comparison so the interface stays responsive
- Read-only processing: input documents are never changed

## Supported formats

- DOCX via `python-docx`
- PDF via `PyMuPDF`

PDF extraction focuses on text and uses PyMuPDF's positional blocks.

## Installation and run

```bash
git clone https://github.com/Restitutor2025/Guide-Comparison.git
cd Guide-Comparison
python run.py
```

`run.py` checks for required modules before importing the application. Missing dependencies are installed from `requirements.txt` using the current Python interpreter.

## Usage

1. Drop the previous `.docx` or `.pdf` into OLD, or select it with **Select Old File**.
2. Drop the latest document into NEW, or select it with **Select New File**.
3. Comparison starts automatically once both documents are present.
4. Drop a replacement on either side to compare again automatically.

Use **Swap OLD ↔ NEW** if the versions were reversed. **Clear** removes a document from the comparison but never deletes or alters the source file.

## Highlight meaning

- Green / `ADDED`: content exists only in NEW.
- Red / `REMOVED`: content exists only in OLD.
- Yellow / `MODIFIED`: corresponding content exists on both sides but changed. Darker yellow marks changed text or cells.
- White/light gray / `UNCHANGED`: normalized comparison text is equal.

## Scrolling controls

- Drag or wheel inside OLD to move only OLD.
- Drag or wheel inside NEW to move only NEW.
- Drag or wheel on the center gutter to apply the same delta to both sides.
- **Previous Change** and **Next Change** align both views to a changed pair.

## Tests

Run the standard-library test suite:

```bash
python -m unittest discover -s tests -v
```

Tests cover insertion/deletion realignment, Korean numeric edits, inline differences, table row/cell changes, empty/merged-cell representations, DOCX XML order, PDF extraction, unsupported files, and corrupt documents.

## Known limitations

- OCR and scanned-PDF recognition are not supported; a warning is shown when little extractable text is found.
- Image, diagram, drawing, and visual-layout differences are not compared.
- PDF table structure is treated as positional text in this MVP; DOCX tables receive structured row/cell comparison.
- DOCX has no reliable rendered page count without a layout engine, so the UI displays `DOCX` instead.
- Very large documents are rendered as cached block widgets after comparison; viewport virtualization is not yet implemented.
- Password-protected PDFs are rejected.
