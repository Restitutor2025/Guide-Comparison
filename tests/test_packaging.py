import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guide_comparison.parsers.docx_parser import _find_soffice


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_windows_libreoffice_install_path_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            program_files = Path(folder)
            soffice = program_files / "LibreOffice" / "program" / "soffice.exe"
            soffice.parent.mkdir(parents=True)
            soffice.touch()
            with (
                patch("guide_comparison.parsers.docx_parser.sys.platform", "win32"),
                patch("guide_comparison.parsers.docx_parser.shutil.which", return_value=None),
                patch.dict(os.environ, {"PROGRAMFILES": str(program_files)}, clear=True),
            ):
                self.assertEqual(_find_soffice(), str(soffice))

    def test_windows_installer_inputs_are_present(self):
        expected = (
            "packaging/windows_launcher.py",
            "packaging/GuideComparison.spec",
            "packaging/GuideComparison.iss",
            "packaging/build_windows.ps1",
            ".github/workflows/build-windows-installer.yml",
            "THIRD_PARTY_NOTICES.md",
        )
        self.assertTrue(all((PROJECT_ROOT / item).is_file() for item in expected))

    def test_bundled_macos_libreoffice_is_detected(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "Guide Comparison.app" / "Contents" / "MacOS" / "GuideComparison"
            soffice = executable.parent.parent / "Resources" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
            soffice.parent.mkdir(parents=True)
            soffice.touch()
            with (
                patch("guide_comparison.parsers.docx_parser.sys.executable", str(executable)),
                patch("guide_comparison.parsers.docx_parser.sys.frozen", True, create=True),
                patch("guide_comparison.parsers.docx_parser.shutil.which", return_value=None),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(_find_soffice(), str(soffice.resolve()))

    def test_macos_bundle_inputs_are_present(self):
        self.assertTrue((PROJECT_ROOT / "packaging" / "GuideComparison-macos.spec").is_file())
        self.assertTrue((PROJECT_ROOT / "packaging" / "build_macos.sh").is_file())

    def test_installer_bundles_libreoffice_and_app(self):
        installer = (PROJECT_ROOT / "packaging" / "GuideComparison.iss").read_text(encoding="utf-8")
        self.assertIn('Source: "..\\dist\\GuideComparison\\*"', installer)
        self.assertIn('DestName: "LibreOffice.msi"', installer)
        self.assertIn('Filename: "{sys}\\msiexec.exe"', installer)


if __name__ == "__main__":
    unittest.main()
