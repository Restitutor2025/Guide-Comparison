from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import AlignedPair, DiffStatus, DocumentBlock, ParsedDocument, TableBlock, TextBlock
from .table_diff import compare_tables
from .text_diff import inline_diff_blocks, matching_text, normalize_text, similarity


MODIFIED_SIMILARITY_THRESHOLD = 0.55
LOCAL_STRUCTURED_SIMILARITY_THRESHOLD = 0.52
_STRUCTURE_PREFIX = re.compile(r"^\s*(※|☞|[①-⑳➀-➉]|[○◯ㅇ●•]|-|\*|\d+[.)]|[가-하][.)])")


def block_key(block: DocumentBlock) -> str:
    if isinstance(block, TableBlock):
        return "\n".join(" | ".join(normalize_text(c) for c in row) for row in block.rows)
    return matching_text(block.text)


def structural_key(block: DocumentBlock | None) -> tuple[str, ...]:
    return tuple(getattr(block, "structure_path", ()) or ())


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
    return _reconcile_layout_fragments(_reconcile_moved_blocks(pairs))


def _compatible(old: DocumentBlock, new: DocumentBlock) -> bool:
    return isinstance(old, TableBlock) == isinstance(new, TableBlock)


def _structure_kind(block: DocumentBlock) -> str:
    if isinstance(block, TableBlock):
        return "table"
    marker = _STRUCTURE_PREFIX.match(block.text)
    return marker.group(1) if marker else block.block_type


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
    old_structure_counts = {key: sum(structural_key(block) == key for block in old_blocks) for key in map(structural_key, old_blocks) if key}
    new_structure_counts = {key: sum(structural_key(block) == key for block in new_blocks) for key in map(structural_key, new_blocks) if key}

    def structurally_identical(old: DocumentBlock, new: DocumentBlock) -> bool:
        key = structural_key(old)
        return bool(
            key
            and key == structural_key(new)
            and old_structure_counts.get(key) == new_structure_counts.get(key) == 1
            and _compatible(old, new)
        )

    gap = 0.72
    cost = [[0.0] * (n + 1) for _ in range(m + 1)]
    move = [[""] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        cost[i][0], move[i][0] = i * gap, "remove"
    for j in range(1, n + 1):
        cost[0][j], move[0][j] = j * gap, "add"
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            old_block, new_block = old_blocks[i - 1], new_blocks[j - 1]
            score = similarity(block_key(old_block), block_key(new_block)) if _compatible(old_block, new_block) else 0.0
            if structurally_identical(old_block, new_block):
                modify_cost = cost[i - 1][j - 1] + 0.12 + 0.28 * (1.0 - score)
            else:
                modify_cost = cost[i - 1][j - 1] + (1.0 - score if score >= MODIFIED_SIMILARITY_THRESHOLD else 2 * gap + 0.01)
            choices = ((modify_cost, "modify"), (cost[i - 1][j] + gap, "remove"), (cost[i][j - 1] + gap, "add"))
            cost[i][j], move[i][j] = min(choices, key=lambda item: item[0])
    result: list[AlignedPair] = []
    i, j = m, n
    while i or j:
        action = move[i][j]
        if action == "modify":
            score = similarity(block_key(old_blocks[i - 1]), block_key(new_blocks[j - 1]))
            if score >= MODIFIED_SIMILARITY_THRESHOLD or structurally_identical(old_blocks[i - 1], new_blocks[j - 1]):
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


def _reconcile_moved_blocks(pairs: list[AlignedPair]) -> list[AlignedPair]:
    """Pair confidently moved blocks left behind by the order-preserving matcher.

    Exact, unique text is safe to reconnect. Fuzzy matches require a high score,
    or a nearby already-confirmed moved block on both sides. Ambiguous content is
    intentionally left as removed/added so a possible change is never hidden.
    """
    removed = [index for index, pair in enumerate(pairs) if pair.status == DiffStatus.REMOVED]
    added = [index for index, pair in enumerate(pairs) if pair.status == DiffStatus.ADDED]
    if not removed or not added:
        return pairs

    matched: dict[int, tuple[int, bool]] = {}
    used_added: set[int] = set()

    old_by_structure: dict[tuple[str, ...], list[int]] = {}
    new_by_structure: dict[tuple[str, ...], list[int]] = {}
    for index in removed:
        key = structural_key(pairs[index].old_block)
        if key:
            old_by_structure.setdefault(key, []).append(index)
    for index in added:
        key = structural_key(pairs[index].new_block)
        if key:
            new_by_structure.setdefault(key, []).append(index)

    # A unique full heading/list path is a stronger identity than position.
    # Repeated paths remain unresolved and fall through to text/context matching.
    for key, old_indices in old_by_structure.items():
        new_indices = new_by_structure.get(key, [])
        if len(old_indices) == len(new_indices) == 1:
            old_index, new_index = old_indices[0], new_indices[0]
            old_block, new_block = pairs[old_index].old_block, pairs[new_index].new_block
            if _compatible(old_block, new_block):
                exact = block_key(old_block) == block_key(new_block)
                matched[old_index] = (new_index, exact)
                used_added.add(new_index)

    old_by_key: dict[str, list[int]] = {}
    new_by_key: dict[str, list[int]] = {}
    for index in removed:
        key = block_key(pairs[index].old_block)
        old_by_key.setdefault(key, []).append(index)
    for index in added:
        key = block_key(pairs[index].new_block)
        new_by_key.setdefault(key, []).append(index)

    # PDF extraction order can move a whole table independently of nearby
    # paragraphs. Equal cell values remain the same content even when they are
    # very short (for example "A", "국가", or "-"). Pair equal-count groups
    # geometrically instead of treating the relocated table as new/deleted.
    for key, old_indices in old_by_key.items():
        new_indices = new_by_key.get(key, [])
        if not key or len(old_indices) != len(new_indices):
            continue
        if not all(
            isinstance(pairs[index].old_block, TextBlock)
            and pairs[index].old_block.block_type == "table_cell"
            for index in old_indices
        ) or not all(
            isinstance(pairs[index].new_block, TextBlock)
            and pairs[index].new_block.block_type == "table_cell"
            for index in new_indices
        ):
            continue

        def geometry(index: int, old_side: bool):
            block = pairs[index].old_block if old_side else pairs[index].new_block
            rect = block.rects[0] if block.rects else (0.0, 0.0, 0.0, 0.0)
            return (block.page or 0, rect[1], rect[0])

        for old_index, new_index in zip(
            sorted(old_indices, key=lambda index: geometry(index, True)),
            sorted(new_indices, key=lambda index: geometry(index, False)),
        ):
            if old_index not in matched and new_index not in used_added:
                matched[old_index] = (new_index, True)
                used_added.add(new_index)

    for key, old_indices in old_by_key.items():
        new_indices = new_by_key.get(key, [])
        old_block = pairs[old_indices[0]].old_block if len(old_indices) == 1 else None
        new_block = pairs[new_indices[0]].new_block if len(new_indices) == 1 else None
        minimum_length = 3 if (
            isinstance(old_block, TextBlock)
            and isinstance(new_block, TextBlock)
            and old_block.block_type == new_block.block_type == "table_cell"
        ) else 12
        if len(key) >= minimum_length and len(old_indices) == len(new_indices) == 1:
            old_index, new_index = old_indices[0], new_indices[0]
            if old_index not in matched and new_index not in used_added and _compatible(pairs[old_index].old_block, pairs[new_index].new_block):
                matched[old_index] = (new_index, True)
                used_added.add(new_index)

    def candidate_scores(old_index: int):
        old_block = pairs[old_index].old_block
        return sorted(
            (
                (similarity(block_key(old_block), block_key(pairs[new_index].new_block)), new_index)
                for new_index in added
                if new_index not in used_added and _compatible(old_block, pairs[new_index].new_block)
            ),
            reverse=True,
        )

    for old_index in removed:
        if old_index in matched or len(block_key(pairs[old_index].old_block)) < 12:
            continue
        candidates = candidate_scores(old_index)
        if not candidates:
            continue
        best_score, best_index = candidates[0]
        next_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score >= 0.86 and best_score - next_score >= 0.08:
            matched[old_index] = (best_index, False)
            used_added.add(best_index)

    # A heavily rewritten item can lose the global dynamic-programming match.
    # Reconnect only nearby items on the same page with the same structural
    # marker, and only when the best candidate is clearly better than the next.
    for old_index in removed:
        if old_index in matched or len(block_key(pairs[old_index].old_block)) < 20:
            continue
        old_block = pairs[old_index].old_block
        candidates = sorted(
            (
                (similarity(block_key(old_block), block_key(pairs[new_index].new_block)), new_index)
                for new_index in added
                if new_index not in used_added
                and abs(new_index - old_index) <= 20
                and getattr(old_block, "page", None) == getattr(pairs[new_index].new_block, "page", None)
                and _compatible(old_block, pairs[new_index].new_block)
                and _structure_kind(old_block) == _structure_kind(pairs[new_index].new_block)
            ),
            reverse=True,
        )
        if not candidates:
            continue
        best_score, best_index = candidates[0]
        next_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score >= LOCAL_STRUCTURED_SIMILARITY_THRESHOLD and best_score - next_score >= 0.08:
            matched[old_index] = (best_index, False)
            used_added.add(best_index)

    # A revised section can move across a page break. Use the structural path
    # as a guardrail, but require the same explicit item marker, a shared top
    # heading, nearby pages, and an unambiguous text candidate.
    def heading_context(block: DocumentBlock) -> tuple[str, ...]:
        return tuple(item for item in structural_key(block) if item.startswith("heading:"))

    for old_index in removed:
        if old_index in matched or len(block_key(pairs[old_index].old_block)) < 20:
            continue
        old_block = pairs[old_index].old_block
        old_marker = getattr(old_block, "marker", None)
        old_headings = heading_context(old_block)
        old_page = getattr(old_block, "page", None)
        if not old_marker or not old_headings or old_page is None:
            continue
        candidates = sorted(
            (
                (similarity(block_key(old_block), block_key(pairs[new_index].new_block)), new_index)
                for new_index in added
                if new_index not in used_added
                and _compatible(old_block, pairs[new_index].new_block)
                and getattr(pairs[new_index].new_block, "marker", None) == old_marker
                and heading_context(pairs[new_index].new_block)[:1] == old_headings[:1]
                and getattr(pairs[new_index].new_block, "page", None) is not None
                and abs(pairs[new_index].new_block.page - old_page) <= 3
            ),
            reverse=True,
        )
        if not candidates:
            continue
        best_score, best_index = candidates[0]
        next_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if best_score >= 0.60 and best_score - next_score >= 0.10:
            matched[old_index] = (best_index, False)
            used_added.add(best_index)

    # Recover the changed edges of an otherwise confidently matched moved run.
    made_progress = True
    while made_progress:
        made_progress = False
        anchors = [(old_index, new_index) for old_index, (new_index, _exact) in matched.items()]
        for old_index in removed:
            if old_index in matched or len(block_key(pairs[old_index].old_block)) < 12:
                continue
            candidates = candidate_scores(old_index)
            for score, new_index in candidates:
                if score < 0.65:
                    break
                if any(abs(old_index - anchor_old) <= 2 and abs(new_index - anchor_new) <= 2 for anchor_old, anchor_new in anchors):
                    matched[old_index] = (new_index, False)
                    used_added.add(new_index)
                    made_progress = True
                    break

    if not matched:
        return pairs

    result: list[AlignedPair] = []
    dropped_added = {new_index for new_index, _exact in matched.values()}
    for index, pair in enumerate(pairs):
        if index in dropped_added:
            continue
        match = matched.get(index)
        if match is None:
            result.append(pair)
            continue
        new_index, exact = match
        old_block, new_block = pair.old_block, pairs[new_index].new_block
        result.append(
            AlignedPair(old_block, new_block, DiffStatus.UNCHANGED)
            if exact
            else _pair_modified(old_block, new_block)
        )
    return result


def _reconcile_layout_fragments(pairs: list[AlignedPair]) -> list[AlignedPair]:
    """Ignore table-cell split/merge differences with identical combined text."""
    dropped: set[int] = set()
    for index, pair in enumerate(pairs):
        if (
            pair.status != DiffStatus.MODIFIED
            or not isinstance(pair.old_block, TextBlock)
            or not isinstance(pair.new_block, TextBlock)
            or pair.old_block.block_type != "table_cell"
            or pair.new_block.block_type != "table_cell"
        ):
            continue
        old_key, new_key = block_key(pair.old_block), block_key(pair.new_block)
        for fragment_index, fragment_pair in enumerate(pairs):
            if fragment_index in dropped or fragment_index == index:
                continue
            if fragment_pair.status == DiffStatus.ADDED and isinstance(fragment_pair.new_block, TextBlock):
                fragment = fragment_pair.new_block
                if fragment.block_type != "table_cell" or fragment.page != pair.new_block.page:
                    continue
                fragment_key = block_key(fragment)
                if old_key in {new_key + fragment_key, fragment_key + new_key}:
                    pair.status = DiffStatus.UNCHANGED
                    pair.old_inline = []
                    pair.new_inline = []
                    dropped.add(fragment_index)
                    break
            elif fragment_pair.status == DiffStatus.REMOVED and isinstance(fragment_pair.old_block, TextBlock):
                fragment = fragment_pair.old_block
                if fragment.block_type != "table_cell" or fragment.page != pair.old_block.page:
                    continue
                fragment_key = block_key(fragment)
                if new_key in {old_key + fragment_key, fragment_key + old_key}:
                    pair.status = DiffStatus.UNCHANGED
                    pair.old_inline = []
                    pair.new_inline = []
                    dropped.add(fragment_index)
                    break

    # A table can move to another page and PDF extraction can split its last
    # row into two cells on one side while joining it into one cell on the
    # other. At that point the cells are separate REMOVED/ADDED pairs rather
    # than a nearby MODIFIED pair, so reconcile unique same-row concatenations.
    def unresolved_cells(status: DiffStatus, old_side: bool):
        entries = []
        for index, pair in enumerate(pairs):
            block = pair.old_block if old_side else pair.new_block
            if (
                index not in dropped
                and pair.status == status
                and isinstance(block, TextBlock)
                and block.block_type == "table_cell"
                and block.page is not None
            ):
                rect = block.rects[0] if block.rects else None
                entries.append((index, block, rect))
        return sorted(entries, key=lambda item: (
            item[1].page,
            item[2][1] if item[2] else item[0],
            item[2][0] if item[2] else item[0],
        ))

    def same_row(left, right) -> bool:
        if left[1].page != right[1].page or left[2] is None or right[2] is None:
            return False
        left_rect, right_rect = left[2], right[2]
        left_center = (left_rect[1] + left_rect[3]) / 2
        right_center = (right_rect[1] + right_rect[3]) / 2
        height = max(left_rect[3] - left_rect[1], right_rect[3] - right_rect[1], 1.0)
        return abs(left_center - right_center) <= height * 0.65

    def candidate_groups(entries):
        groups = []
        for position, entry in enumerate(entries):
            groups.append(((entry[0],), block_key(entry[1])))
            if position + 1 < len(entries) and same_row(entry, entries[position + 1]):
                next_entry = entries[position + 1]
                ordered = sorted((entry, next_entry), key=lambda item: item[2][0])
                groups.append((
                    tuple(item[0] for item in ordered),
                    "".join(block_key(item[1]) for item in ordered),
                ))
        return groups

    old_groups = candidate_groups(unresolved_cells(DiffStatus.REMOVED, True))
    new_groups = candidate_groups(unresolved_cells(DiffStatus.ADDED, False))
    old_by_key: dict[str, list[tuple[int, ...]]] = {}
    new_by_key: dict[str, list[tuple[int, ...]]] = {}
    for indices, key in old_groups:
        if len(key) >= 8:
            old_by_key.setdefault(key, []).append(indices)
    for indices, key in new_groups:
        if len(key) >= 8:
            new_by_key.setdefault(key, []).append(indices)

    consumed: set[int] = set()
    for key, old_matches in old_by_key.items():
        new_matches = new_by_key.get(key, [])
        if len(old_matches) != 1 or len(new_matches) != 1:
            continue
        old_indices, new_indices = old_matches[0], new_matches[0]
        if len(old_indices) == len(new_indices) or consumed.intersection((*old_indices, *new_indices)):
            continue
        keeper = old_indices[0]
        pairs[keeper].new_block = pairs[new_indices[0]].new_block
        pairs[keeper].status = DiffStatus.UNCHANGED
        pairs[keeper].old_inline = []
        pairs[keeper].new_inline = []
        dropped.update(old_indices[1:])
        dropped.update(new_indices)
        consumed.update((*old_indices, *new_indices))
    return [pair for index, pair in enumerate(pairs) if index not in dropped]
