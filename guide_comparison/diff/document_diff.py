from __future__ import annotations

from difflib import SequenceMatcher

from .models import AlignedPair, DiffStatus, DocumentBlock, ParsedDocument, TableBlock, TextBlock
from .table_diff import compare_tables
from .text_diff import inline_diff_blocks, matching_text, normalize_text, similarity


MODIFIED_SIMILARITY_THRESHOLD = 0.55


def block_key(block: DocumentBlock) -> str:
    if isinstance(block, TableBlock):
        return "\n".join(" | ".join(normalize_text(c) for c in row) for row in block.rows)
    return matching_text(block.text)


def compare_documents(old: ParsedDocument, new: ParsedDocument) -> list[AlignedPair]:
    matcher = SequenceMatcher(None, [block_key(b) for b in old.blocks], [block_key(b) for b in new.blocks], autojunk=False)
    pairs: list[AlignedPair] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_slice, new_slice = old.blocks[i1:i2], new.blocks[j1:j2]
        if tag == "equal":
            pairs.extend(AlignedPair(a, b, DiffStatus.UNCHANGED) for a, b in zip(old_slice, new_slice))
        elif tag == "delete":
            pairs.extend(AlignedPair(block, None, DiffStatus.REMOVED) for block in old_slice)
        elif tag == "insert":
            pairs.extend(AlignedPair(None, block, DiffStatus.ADDED) for block in new_slice)
        else:
            pairs.extend(_align_replacement(old_slice, new_slice))
    return pairs


def _compatible(old: DocumentBlock, new: DocumentBlock) -> bool:
    return isinstance(old, TableBlock) == isinstance(new, TableBlock)


def _pair_modified(old: DocumentBlock, new: DocumentBlock) -> AlignedPair:
    pair = AlignedPair(old, new, DiffStatus.MODIFIED)
    if isinstance(old, TableBlock) and isinstance(new, TableBlock):
        pair.table_rows = compare_tables(old, new)
    elif isinstance(old, TextBlock) and isinstance(new, TextBlock):
        pair.old_inline, pair.new_inline = inline_diff_blocks(old, new)
    return pair


def _align_replacement(old_blocks: list[DocumentBlock], new_blocks: list[DocumentBlock]) -> list[AlignedPair]:
    """Align a replacement region using a small dynamic-programming edit graph."""
    m, n = len(old_blocks), len(new_blocks)
    gap = 0.72
    cost = [[0.0] * (n + 1) for _ in range(m + 1)]
    move = [[""] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        cost[i][0], move[i][0] = i * gap, "remove"
    for j in range(1, n + 1):
        cost[0][j], move[0][j] = j * gap, "add"
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            score = similarity(block_key(old_blocks[i - 1]), block_key(new_blocks[j - 1])) if _compatible(old_blocks[i - 1], new_blocks[j - 1]) else 0.0
            modify_cost = cost[i - 1][j - 1] + (1.0 - score if score >= MODIFIED_SIMILARITY_THRESHOLD else 2 * gap + 0.01)
            choices = ((modify_cost, "modify"), (cost[i - 1][j] + gap, "remove"), (cost[i][j - 1] + gap, "add"))
            cost[i][j], move[i][j] = min(choices, key=lambda item: item[0])
    result: list[AlignedPair] = []
    i, j = m, n
    while i or j:
        action = move[i][j]
        if action == "modify":
            score = similarity(block_key(old_blocks[i - 1]), block_key(new_blocks[j - 1]))
            if score >= MODIFIED_SIMILARITY_THRESHOLD:
                result.append(_pair_modified(old_blocks[i - 1], new_blocks[j - 1]))
            else:
                result.extend((AlignedPair(old_blocks[i - 1], None, DiffStatus.REMOVED), AlignedPair(None, new_blocks[j - 1], DiffStatus.ADDED)))
            i -= 1; j -= 1
        elif action == "remove":
            result.append(AlignedPair(old_blocks[i - 1], None, DiffStatus.REMOVED)); i -= 1
        else:
            result.append(AlignedPair(None, new_blocks[j - 1], DiffStatus.ADDED)); j -= 1
    result.reverse()
    return result
