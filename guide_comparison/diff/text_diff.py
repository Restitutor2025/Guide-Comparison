from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import InlineChunk


_WHITESPACE = re.compile(r"\s+")
# Keep digit runs separate from words so changes such as Korean "30일" -> "40일"
# highlight the value rather than the unchanged suffix.
_TOKEN = re.compile(r"\s+|[0-9]+|[^\W\d_]+|_+|[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Normalize layout noise without discarding meaningful punctuation or case."""
    return _WHITESPACE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def similarity(old: str, new: str) -> float:
    return SequenceMatcher(None, normalize_text(old), normalize_text(new), autojunk=False).ratio()


def inline_diff(old: str, new: str) -> tuple[list[InlineChunk], list[InlineChunk]]:
    old_tokens, new_tokens = _TOKEN.findall(old), _TOKEN.findall(new)
    matcher = SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    old_result: list[InlineChunk] = []
    new_result: list[InlineChunk] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if i1 != i2:
            old_result.append(InlineChunk("".join(old_tokens[i1:i2]), tag != "equal"))
        if j1 != j2:
            new_result.append(InlineChunk("".join(new_tokens[j1:j2]), tag != "equal"))
    return _coalesce(old_result), _coalesce(new_result)


def _coalesce(chunks: list[InlineChunk]) -> list[InlineChunk]:
    result: list[InlineChunk] = []
    for chunk in chunks:
        if chunk.text and result and result[-1].changed == chunk.changed:
            result[-1].text += chunk.text
        elif chunk.text:
            result.append(chunk)
    return result
