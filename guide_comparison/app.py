from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from guide_comparison.ui.main_window import MainWindow


STYLESHEET = """
QMainWindow { background: #eef1f5; }
QWidget { color: #20262e; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QPushButton { background: white; border: 1px solid #c8d0da; border-radius: 6px; padding: 6px 11px; min-height: 18px; }
QPushButton:hover { background: #f1f6fb; border-color: #8ca9c6; }
QPushButton:pressed { background: #e5edf6; }
QPushButton:disabled { color: #9aa3ad; background: #f2f4f6; border-color: #d9dee4; }
QPushButton#primaryButton { background: #2468a9; color: white; border-color: #2468a9; font-weight: 700; }
QPushButton#primaryButton:hover { background: #1e5d98; border-color: #1e5d98; }
QPushButton#exportButton { background: #e9f6ef; color: #176b41; border-color: #8ac7a6; font-weight: 700; }
QPushButton#exportButton:hover { background: #dff1e7; border-color: #5eae83; }
QPushButton#exportButton:disabled { background: #f2f4f6; color: #9aa3ad; border-color: #d9dee4; }
QFrame#commandBar { background: white; border: 1px solid #d9dfe6; border-radius: 10px; }
QFrame#toolbarGroup { background: #f7f9fb; border: 1px solid #e0e5eb; border-radius: 8px; }
QLabel#brandTitle { color: #18222d; font-size: 17px; font-weight: 700; }
QLabel#brandSubtitle { color: #697786; font-size: 11px; }
QFrame#dropArea { background: #fafbfd; border: 2px dashed #aab5c1; border-radius: 8px; margin: 2px 8px 8px 8px; }
QFrame#dropArea:hover { background: #eef6ff; border-color: #4f8fcf; }
QFrame#paneHeader { background: white; border: 1px solid #d9dfe6; border-radius: 8px; }
QLabel#paneTitle { font-size: 15px; font-weight: 700; }
QLabel#paneRoleBadge { background: #e8eef5; color: #4d6175; border-radius: 9px; padding: 2px 7px; font-size: 11px; font-weight: 700; }
QLabel#fileInfo { color: #536170; }
QLabel#differencesLabel { font-weight: 700; padding-left: 2px; }
QLabel#differenceCountLabel { color: #536170; }
QLabel#differenceLegend { color: #4a5662; padding: 0 2px 0 6px; font-size: 12px; }
QLabel#pageModeStatus { background: #e8edf2; color: #536170; border: 1px solid #cbd2da; border-radius: 10px; padding: 4px 9px; font-weight: 700; }
QLabel#pageModeStatus[mode="changes"] { background: #fff4cf; color: #795b00; border-color: #e6c65b; }
QLabel#pageModeStatus[mode="all"] { background: #dceeff; color: #1e5f98; border-color: #77acd8; }
QLabel#pageModeStatus[mode="loading"] { background: #e8edf2; color: #536170; }
QLabel#pageModeStatus[mode="failed"] { background: #ffe5e5; color: #9b3030; border-color: #df9a9a; }
QLineEdit#differencePageEdit { background: white; border: 1px solid #aeb8c2; border-radius: 5px; padding: 4px 5px; font-weight: 700; }
QLineEdit#differencePageEdit:focus { border: 2px solid #4f8fcf; padding: 3px 4px; }
QLabel#differenceTotalLabel { font-weight: 700; }
QPushButton#differenceNavigationButton { font-size: 15px; font-weight: 700; padding: 0; min-height: 0; }
QFrame#loadingOverlay { background: rgba(244, 246, 248, 225); }
QLabel#loadingLabel { color: #245f9e; font-size: 22px; font-weight: 700; padding-top: 12px; }
QLabel#reportReviewTitle { color: #17365d; font-size: 19px; font-weight: 700; }
QLabel#reportReviewGuidance { color: #536170; }
QFrame#reportSourceBar { background: #f3f6f9; border: 1px solid #d9e0e7; border-radius: 7px; }
QLabel#reportSelectionStatus { color: #1f5f92; font-weight: 700; }
QTableWidget#reportReviewTable { background: white; alternate-background-color: #f7f9fb; gridline-color: #d7dde4; border: 1px solid #cbd3dc; }
QTableWidget#reportReviewTable::item { padding: 6px; }
QHeaderView::section { background: #dce6f1; color: #263645; border: 0; border-right: 1px solid #c4ced8; border-bottom: 1px solid #b8c4d0; padding: 7px 5px; font-weight: 700; }
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
