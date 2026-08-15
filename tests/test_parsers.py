import tempfile
import unittest
from pathlib import Path

from guide_comparison.diff.models import TableBlock, TextBlock
from guide_comparison.parsers import DocumentParseError, parse_document
from guide_comparison.parsers.docx_parser import _extract_docx_blocks


class ParserTests(unittest.TestCase):
    def test_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.txt"; path.write_text("hello")
            with self.assertRaises(DocumentParseError):
                parse_document(path)

    def test_docx_preserves_paragraph_table_order(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "order.docx"
            doc = Document(); doc.add_paragraph("Before"); table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "A"; table.cell(0, 1).text = "B"; doc.add_paragraph("After"); doc.save(path)
            source_blocks = _extract_docx_blocks(path)
            self.assertEqual([type(b) for b in source_blocks], [TextBlock, TableBlock, TextBlock])
            parsed = parse_document(path)
            self.assertEqual(parsed.page_count, 1)
            self.assertTrue(parsed.render_path and parsed.render_path.is_file())
            self.assertIn("Before", " ".join(block.text for block in parsed.blocks))

    def test_pdf_page_count_and_text(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            doc = fitz.open(); page = doc.new_page(); page.insert_text((72, 72), "Guide paragraph"); doc.save(path); doc.close()
            parsed = parse_document(path)
            self.assertEqual(parsed.page_count, 1)
            self.assertIn("Guide paragraph", [b.text for b in parsed.blocks])
            self.assertEqual(parsed.render_path, path)
            self.assertTrue(next(b for b in parsed.blocks if b.text == "Guide paragraph").rects)

    def test_pdf_merges_wrapped_lines_but_keeps_separate_paragraphs(self):
        try:
            import pymupdf as fitz
        except ImportError:
            self.skipTest("PyMuPDF unavailable")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrapped.pdf"
            doc = fitz.open(); page = doc.new_page()
            page.insert_text((72, 72), "First paragraph continues")
            page.insert_text((72, 86), "and ends here.")
            page.insert_text((72, 125), "Separate paragraph.")
            doc.save(path); doc.close()
            parsed = parse_document(path)
            self.assertEqual([block.text for block in parsed.blocks], [
                "First paragraph continues and ends here.",
                "Separate paragraph.",
            ])
            self.assertEqual(len(parsed.blocks[0].rects), 2)
            self.assertTrue(parsed.blocks[0].chars)

    def test_corrupt_files_are_wrapped(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in (".pdf", ".docx"):
                path = Path(folder) / f"bad{suffix}"; path.write_bytes(b"not a document")
                with self.assertRaises(DocumentParseError):
                    parse_document(path)


if __name__ == "__main__":
    unittest.main()
