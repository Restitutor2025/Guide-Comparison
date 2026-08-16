from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypeAlias


class DiffStatus(str, Enum):
    UNCHANGED = "UNCHANGED"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


@dataclass(slots=True)
class TextBlock:
    text: str
    block_type: str = "paragraph"
    page: int | None = None
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    chars: list[tuple[str, float, float, float, float]] = field(default_factory=list)
    structure_path: tuple[str, ...] = ()
    marker: str | None = None


@dataclass(slots=True)
class TableBlock:
    rows: list[list[str]]
    page: int | None = None
    structure_path: tuple[str, ...] = ()
    block_type: str = field(default="table", init=False)


DocumentBlock: TypeAlias = TextBlock | TableBlock


@dataclass(slots=True)
class ParsedDocument:
    path: Path
    blocks: list[DocumentBlock]
    page_count: int | None = None
    warning: str | None = None
    render_path: Path | None = None


@dataclass(slots=True)
class InlineChunk:
    text: str
    changed: bool = False
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    status: DiffStatus = DiffStatus.UNCHANGED


@dataclass(slots=True)
class AlignedRow:
    old_cells: list[str] | None
    new_cells: list[str] | None
    status: DiffStatus
    changed_old_cells: set[int] = field(default_factory=set)
    changed_new_cells: set[int] = field(default_factory=set)


@dataclass(slots=True)
class AlignedPair:
    old_block: DocumentBlock | None
    new_block: DocumentBlock | None
    status: DiffStatus
    old_inline: list[InlineChunk] = field(default_factory=list)
    new_inline: list[InlineChunk] = field(default_factory=list)
    table_rows: list[AlignedRow] = field(default_factory=list)
