from __future__ import annotations

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from .models import DiffStatus, InlineChunk, TextBlock


_WHITESPACE = re.compile(r"\s+")
_MATCH_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)
_PUNCTUATION = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "‐": "-", "‑": "-", "–": "-", "—": "-",
    "ㆍ": "·", "‧": "·", "•": "·", "●": "·", "○": "·",
})
# Keep digit runs separate from words so changes such as Korean "30일" -> "40일"
# highlight the value rather than the unchanged suffix.
_TOKEN = re.compile(r"\s+|[0-9]+|[^\W\d_]+|_+|[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Normalize layout noise without discarding meaningful punctuation or case."""
    return _WHITESPACE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def matching_text(text: str) -> str:
    """Canonical form used for matching, without changing displayed source text."""
    canonical = unicodedata.normalize("NFKC", normalize_text(text)).translate(_PUNCTUATION).casefold()
    # PDF and Word line layout frequently inserts or removes spaces around Korean/Latin text.
    return _MATCH_SPACE.sub("", canonical)


def _token_overlap(old: str, new: str) -> float:
    old_tokens = Counter(_WORD.findall(unicodedata.normalize("NFKC", normalize_text(old)).casefold()))
    new_tokens = Counter(_WORD.findall(unicodedata.normalize("NFKC", normalize_text(new)).casefold()))
    total = sum(old_tokens.values()) + sum(new_tokens.values())
    return 2 * sum((old_tokens & new_tokens).values()) / total if total else 1.0


def similarity(old: str, new: str) -> float:
    old_key, new_key = matching_text(old), matching_text(new)
    if old_key == new_key:
        return 1.0
    character_score = SequenceMatcher(None, old_key, new_key, autojunk=False).ratio()
    return 0.82 * character_score + 0.18 * _token_overlap(old, new)


def inline_diff(old: str, new: str) -> tuple[list[InlineChunk], list[InlineChunk]]:
    old_tokens, new_tokens = _TOKEN.findall(old), _TOKEN.findall(new)
    matcher = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    old_result: list[InlineChunk] = []
    new_result: list[InlineChunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if i1 != i2:
            status = DiffStatus.REMOVED if tag == "delete" else DiffStatus.MODIFIED if tag == "replace" else DiffStatus.UNCHANGED
            old_result.append(InlineChunk("".join(old_tokens[i1:i2]), tag != "equal", status=status))
        if j1 != j2:
            status = DiffStatus.ADDED if tag == "insert" else DiffStatus.MODIFIED if tag == "replace" else DiffStatus.UNCHANGED
            new_result.append(InlineChunk("".join(new_tokens[j1:j2]), tag != "equal", status=status))
    return _coalesce(old_result), _coalesce(new_result)


def _character_units(block: TextBlock):
    units = []
    for char in block.chars:
        key = matching_text(char[0])
        if key:
            units.append((key, char))
    return units


def _character_tokens(block: TextBlock):
    """Group positioned PDF characters into semantic comparison tokens."""
    tokens = []
    key_parts = []
    chars = []
    kind = None

    def flush():
        nonlocal key_parts, chars, kind
        if key_parts:
            tokens.append(("".join(key_parts), chars))
        key_parts, chars, kind = [], [], None

    for char in block.chars:
        value = unicodedata.normalize("NFKC", char[0]).translate(_PUNCTUATION).casefold()
        if not value or value.isspace():
            flush()
            continue
        if value.isdigit():
            current_kind = "digit"
        elif all(character.isalpha() for character in value):
            current_kind = "word"
        elif value == "_":
            current_kind = "underscore"
        else:
            current_kind = "punctuation"
        if kind is not None and (current_kind != kind or current_kind == "punctuation"):
            flush()
        kind = current_kind
        key_parts.append(value)
        chars.append(char)
        if current_kind == "punctuation":
            flush()
    flush()
    return tokens


def _character_rects(chars) -> list[tuple[float, float, float, float]]:
    rects: list[list[float]] = []
    for _value, x0, y0, x1, y1 in chars:
        if rects:
            previous = rects[-1]
            height = max(previous[3] - previous[1], y1 - y0, 1.0)
            same_line = abs(((previous[1] + previous[3]) / 2) - ((y0 + y1) / 2)) <= height * 0.35
            if same_line and x0 - previous[2] <= height * 0.65:
                previous[0] = min(previous[0], x0)
                previous[1] = min(previous[1], y0)
                previous[2] = max(previous[2], x1)
                previous[3] = max(previous[3], y1)
                continue
        rects.append([x0, y0, x1, y1])
    return [tuple(rect) for rect in rects]


def _display_rects(chars, block: TextBlock, *, changed: bool) -> list[tuple[float, float, float, float]]:
    """Return display rectangles without inferring character ownership from geometry.

    PDF glyph boxes can overlap their neighbours.  A changed digit immediately
    before a Korean unit, for example ``3개월``, must therefore be associated
    with a token by its source character rather than by intersecting rectangles.
    """
    rects = _character_rects(chars)
    if not changed:
        return rects

    key = "".join(matching_text(char[0]) for char in chars)
    if len(key) != 1:
        return rects

    source_char = chars[0]
    for token_key, token_chars in _character_tokens(block):
        if source_char not in token_chars:
            continue
        # A one-letter Korean/Latin edit needs its containing word for context.
        # A changed digit stays numeric; if it belongs to a multi-digit value,
        # show the complete value rather than an adjacent unit or word.
        if key.isalpha() and token_key.isalpha() and len(token_key) > 1:
            return _character_rects(token_chars)
        if key.isdigit() and token_key.isdigit() and len(token_key) > 1:
            return _character_rects(token_chars)
        break
    return rects


def inline_diff_blocks(old: TextBlock, new: TextBlock) -> tuple[list[InlineChunk], list[InlineChunk]]:
    """Compare merged paragraph characters while retaining original PDF rectangles."""
    old_units, new_units = _character_units(old), _character_units(new)
    if not old_units or not new_units:
        return inline_diff(old.text, new.text)

    matcher = SequenceMatcher(
        None,
        [key for key, _char in old_units],
        [key for key, _char in new_units],
        autojunk=False,
    )
    old_result: list[InlineChunk] = []
    new_result: list[InlineChunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if i1 != i2:
            chars = [char for _key, char in old_units[i1:i2]]
            status = DiffStatus.REMOVED if tag == "delete" else DiffStatus.MODIFIED if tag == "replace" else DiffStatus.UNCHANGED
            old_result.append(InlineChunk(
                "".join(char[0] for char in chars),
                tag != "equal",
                _display_rects(chars, old, changed=tag != "equal"),
                status,
            ))
        if j1 != j2:
            chars = [char for _key, char in new_units[j1:j2]]
            status = DiffStatus.ADDED if tag == "insert" else DiffStatus.MODIFIED if tag == "replace" else DiffStatus.UNCHANGED
            new_result.append(InlineChunk(
                "".join(char[0] for char in chars),
                tag != "equal",
                _display_rects(chars, new, changed=tag != "equal"),
                status,
            ))
    old_result, new_result = _coalesce(old_result), _coalesce(new_result)
    return old_result, new_result


def _coalesce(chunks: list[InlineChunk]) -> list[InlineChunk]:
    result: list[InlineChunk] = []
    for chunk in chunks:
        if chunk.text and result and result[-1].changed == chunk.changed and result[-1].status == chunk.status:
            result[-1].text += chunk.text
            result[-1].rects.extend(chunk.rects)
        elif chunk.text:
            result.append(chunk)
    return result
