# Guide Comparison

Guide Comparison is a local, deterministic desktop application for comparing an older work guide with a newer revision. It renders the original pages and overlays text changes without AI, cloud services, or modifying the source files.

## Features

- OLD/NEW drag and drop plus file-picker fallback
- Original PDF/Word page layout instead of reconstructed text cards
- Toggle between all pages and pages containing detected changes
- Every changed page is shown with a real corresponding page on the opposite side
- Selection-like overlays: added (green), removed (red), and modified (yellow), including directional colors inside modified paragraphs
- Lazy page rendering to keep long documents responsive
- Independent hand-drag and wheel scrolling directly over either document page
- Synchronized drag and wheel scrolling from page margins or the center gutter
- Centered `변경점 X/Y` counter with separate previous/next navigation, swap, clear, page-mode toggle, and file replacement
- Background parsing and comparison so the interface stays responsive
- Read-only processing: input documents are never changed

## Supported formats

- PDF via `PyMuPDF`
- DOCX rendered to PDF via LibreOffice, then processed with the same page pipeline

Text extraction uses positional blocks so highlights can be drawn over their original page coordinates. Adjacent non-table PDF blocks are merged into logical paragraphs for comparison while their original character coordinates are retained for precise highlights. LibreOffice is required for DOCX page rendering; its output is very close to Word but is not guaranteed to be pixel-identical to Microsoft Word.

## Installation and run

```bash
git clone https://github.com/Restitutor2025/Guide-Comparison.git
cd Guide-Comparison
python run.py
```

On the first launch, `run.py` creates a project-local `.venv`, restarts itself with that environment's Python interpreter, and installs missing dependencies from `requirements.txt`. Later launches reuse the same isolated environment automatically.

## Windows installer

`GuideComparisonSetup.exe` is an offline x64 installer for Windows 10 or newer. It installs the frozen application and, when LibreOffice is not already present, the bundled LibreOffice MSI used for DOCX page rendering. End users do not need Python, pip, a terminal, or an internet connection.

Build it on an x64 Windows machine with Python and Inno Setup installed:

```powershell
.\packaging\build_windows.ps1
```

The command above creates an unsigned development build. For a distributable build, install a publicly trusted Authenticode code-signing certificate (with its private key) in the Windows certificate store and run:

```powershell
.\packaging\build_windows.ps1 `
  -SigningThumbprint "YOUR_CERTIFICATE_THUMBPRINT" `
  -RequireCodeSigning
```

The release build signs and verifies the frozen application, the Inno Setup uninstaller, and the final installer with SHA-256 and an RFC 3161 timestamp. UPX compression is disabled because packed Python executables are more likely to trigger heuristic antivirus detections. Do not substitute a self-signed certificate for public distribution: recipient PCs will not trust it and it does not establish SmartScreen reputation.

The GitHub Actions workflow intentionally requires the repository secrets `WINDOWS_CERTIFICATE_BASE64` (a base64-encoded PFX) and `WINDOWS_CERTIFICATE_PASSWORD`; it refuses to publish an unsigned artifact. If Microsoft Defender still reports a signed release, submit that exact file as a software-developer false positive through the [Microsoft Security Intelligence file submission portal](https://www.microsoft.com/en-us/wdsi/filesubmission). Do not submit source documents or user data.

The output is `dist\installer\GuideComparisonSetup.exe`. The installer is intentionally large because it contains the complete LibreOffice Windows installer. The same build can be started manually with the **Build Windows Installer** GitHub Actions workflow.

Before distributing the application, review [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). In particular, PyMuPDF is AGPLv3 or commercially licensed, so distribution must comply with the AGPL or use an appropriate commercial license.

## Self-contained macOS application

With LibreOffice installed in `/Applications`, build a single Finder-visible app bundle with:

```bash
zsh packaging/build_macos.sh
```

The output is `executables/Guide Comparison.app`. The complete LibreOffice app is embedded inside the bundle so PDF and DOCX comparison work without a separate LibreOffice installation on the destination Mac. The local build is ad-hoc signed for testing; third-party distribution without Gatekeeper warnings requires Apple Developer ID signing and notarization.

## Usage

1. Drop the previous `.docx` or `.pdf` into OLD, or select it with **Select Old File**.
2. Drop the latest document into NEW, or select it with **Select New File**.
3. Comparison starts automatically once both documents are present.
4. Drop a replacement on either side to compare again automatically.

Use **Swap OLD ↔ NEW** if the versions were reversed. **전체 페이지 보기** toggles from paired changed pages to the complete documents; **변경점 페이지 보기** returns to the paired change view. **Clear** removes a document from the comparison but never deletes or alters the source file.

## Highlight meaning

- Green: content exists only in NEW.
- Red: content exists only in OLD.
- Yellow: corresponding content exists on both sides but changed.
- No highlight: normalized comparison text is equal.

## Scrolling controls

- Drag or wheel directly over an OLD page to move only OLD.
- Drag or wheel directly over a NEW page to move only NEW.
- Drag or wheel over the gray page margins or center gutter to move both sides.
- Use the ↑/↓ buttons below **변경점** to move to the previous or next changed page.
- Multiple highlights on the same page count as one difference target.
- Navigation wraps between the first and last changed pages.

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
