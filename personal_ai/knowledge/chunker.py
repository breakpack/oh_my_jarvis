"""Sliding-window chunker (SPEC.md §8.5 RAG pipeline Chunk stage).

Pure function, no I/O: a character-length sliding window that prefers to
break on a paragraph/sentence/word boundary near the limit instead of
mid-word, with a fixed character overlap between consecutive chunks.
"""

from __future__ import annotations

from typing import TypedDict

from personal_ai.knowledge.parsers import Section


class Chunk(TypedDict):
    content: str
    page: int | None
    section: str | None
    chunk_index: int


def chunk_sections(
    sections: list[Section], max_chars: int = 800, overlap: int = 100
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        for piece in _split(section["content"], max_chars, overlap):
            chunks.append(
                {
                    "content": piece,
                    "page": section["page"],
                    "section": section["section"],
                    "chunk_index": len(chunks),
                }
            )
    return chunks


def _split(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            end = _prefer_boundary(text, start, end)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def _prefer_boundary(text: str, start: int, end: int) -> int:
    """Nudge `end` back to the nearest paragraph/sentence/word break within
    the window, as long as that break isn't so early it'd make a tiny chunk."""
    window = text[start:end]
    for boundary in ("\n\n", ". ", "\n", " "):
        idx = window.rfind(boundary)
        if idx > len(window) // 2:
            return start + idx + len(boundary)
    return end
