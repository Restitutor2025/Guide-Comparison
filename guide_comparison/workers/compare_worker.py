from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from guide_comparison.diff.document_diff import compare_documents
from guide_comparison.parsers import parse_document


log = logging.getLogger(__name__)


class CompareWorker(QObject):
    progress = Signal(str)
    succeeded = Signal(object, object, object)
    failed = Signal(object, object, str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, old_path: Path, new_path: Path):
        super().__init__()
        self.old_path, self.new_path = old_path, new_path

    @Slot()
    def run(self):
        try:
            self.progress.emit("Parsing old document..."); log.info("Parsing old document")
            old = parse_document(self.old_path)
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            self.progress.emit("Parsing new document..."); log.info("Parsing new document")
            new = parse_document(self.new_path)
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            self.progress.emit("Comparing..."); log.info("Aligning document blocks")
            pairs = compare_documents(old, new)
            if QThread.currentThread().isInterruptionRequested():
                self.cancelled.emit()
                return
            self.progress.emit("Rendering...")
            self.succeeded.emit(old, new, pairs)
        except Exception as exc:
            log.exception("Comparison failed")
            self.failed.emit(self.old_path, self.new_path, str(exc))
        finally:
            self.finished.emit()
