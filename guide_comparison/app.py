from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from guide_comparison.ui.main_window import MainWindow


STYLESHEET = """
QMainWindow { background: #f4f6f8; }
QWidget { color: #20262e; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QPushButton { background: white; border: 1px solid #cbd2da; border-radius: 5px; padding: 6px 10px; }
QPushButton:hover { background: #eef3f8; }
QPushButton:disabled { color: #9aa3ad; }
QFrame#dropArea { background: #fafbfd; border: 2px dashed #aab5c1; border-radius: 8px; margin: 2px 8px 8px 8px; }
QFrame#dropArea:hover { background: #eef6ff; border-color: #4f8fcf; }
QLabel#paneTitle { font-size: 17px; font-weight: 700; padding: 8px; }
QLabel#fileInfo { color: #536170; }
QLabel#differencesLabel { font-weight: 700; }
QPushButton#differenceNavigationButton { font-size: 16px; font-weight: 700; padding: 0; }
QFrame#syncGutter { background: #d8dee5; border-left: 1px solid #b9c2cc; border-right: 1px solid #b9c2cc; }
QWidget#pageStack { background: #dfe3e8; }
QScrollBar:vertical { width: 11px; background: #edf0f3; }
QScrollBar::handle:vertical { background: #aeb8c2; border-radius: 5px; min-height: 25px; }
"""


def configure_logging() -> None:
    if os.name == "nt":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "GuideComparison"
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Logs" / "GuideComparison"
    else:
        base_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "guide-comparison"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        base_dir = Path(tempfile.gettempdir()) / "guide-comparison"
        base_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(base_dir / "guide_comparison.log", encoding="utf-8"), logging.StreamHandler()],
    )


def run() -> int:
    configure_logging()
    logging.getLogger(__name__).info("Application started")
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Guide Comparison")
    application.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return application.exec()
