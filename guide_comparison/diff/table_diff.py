from __future__ import annotations

from difflib import SequenceMatcher

from .models import AlignedRow, DiffStatus, TableBlock
from .text_diff import normalize_text, similarity


ROW_MODIFIED_THRESHOLD = 0.45


def row_key(row: list[str]) -> str:
    return " | ".join(normalize_text(cell) for cell in row)


def compare_tables(old: TableBlock, new: TableBlock) -> list[AlignedRow]:
    matcher = SequenceMatcher(None, [row_key(r) for r in old.rows], [row_key(r) for r in new.rows], autojunk=False)
    result: list[AlignedRow] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(AlignedRow(old.rows[i], new.rows[j], DiffStatus.UNCHANGED) for i, j in zip(range(i1, i2), range(j1, j2)))
        elif tag == "delete":
            result.extend(AlignedRow(old.rows[i], None, DiffStatus.REMOVED) for i in range(i1, i2))
        elif tag == "insert":
            result.extend(AlignedRow(None, new.rows[j], DiffStatus.ADDED) for j in range(j1, j2))
        else:
            result.extend(_align_replaced_rows(old.rows[i1:i2], new.rows[j1:j2]))
    return result


def _align_replaced_rows(old_rows: list[list[str]], new_rows: list[list[str]]) -> list[AlignedRow]:
    result: list[AlignedRow] = []
    while old_rows and new_rows:
        score = similarity(row_key(old_rows[0]), row_key(new_rows[0]))
        if score >= ROW_MODIFIED_THRESHOLD:
            old_row, new_row = old_rows.pop(0), new_rows.pop(0)
            max_cells = max(len(old_row), len(new_row))
            changed = {i for i in range(max_cells) if normalize_text(old_row[i] if i < len(old_row) else "") != normalize_text(new_row[i] if i < len(new_row) else "")}
            result.append(AlignedRow(old_row, new_row, DiffStatus.MODIFIED, set(changed), set(changed)))
        else:
            old_best = similarity(row_key(old_rows[0]), row_key(new_rows[1])) if len(new_rows) > 1 else -1
            new_best = similarity(row_key(old_rows[1]), row_key(new_rows[0])) if len(old_rows) > 1 else -1
            if old_best > new_best:
                result.append(AlignedRow(None, new_rows.pop(0), DiffStatus.ADDED))
            else:
                result.append(AlignedRow(old_rows.pop(0), None, DiffStatus.REMOVED))
    result.extend(AlignedRow(row, None, DiffStatus.REMOVED) for row in old_rows)
    result.extend(AlignedRow(None, row, DiffStatus.ADDED) for row in new_rows)
    return result

