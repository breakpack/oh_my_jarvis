"""Unit tests for personal_ai.knowledge.chunker (SPEC.md §8.5 Chunk stage).
Pure function, no I/O, no mocking needed.
"""

from __future__ import annotations

from personal_ai.knowledge.chunker import chunk_sections


def test_short_section_becomes_a_single_chunk():
    sections = [{"content": "short text", "page": 1, "section": "intro"}]

    chunks = chunk_sections(sections, max_chars=800, overlap=100)

    assert len(chunks) == 1
    assert chunks[0] == {
        "content": "short text",
        "page": 1,
        "section": "intro",
        "chunk_index": 0,
    }


def test_empty_section_produces_no_chunks():
    sections = [{"content": "   ", "page": None, "section": None}]

    assert chunk_sections(sections) == []


def test_long_text_is_split_into_multiple_chunks_within_max_chars():
    long_text = " ".join(f"word{i}" for i in range(500))  # well over 800 chars
    sections = [{"content": long_text, "page": 2, "section": "body"}]

    chunks = chunk_sections(sections, max_chars=100, overlap=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk["content"]) <= 100
        assert chunk["page"] == 2
        assert chunk["section"] == "body"
    # Every chunk gets covered start to finish.
    assert long_text.startswith(chunks[0]["content"])
    assert chunks[-1]["content"] in long_text


def test_chunk_index_is_sequential_and_continues_across_sections():
    sections = [
        {"content": "first section", "page": 1, "section": None},
        {"content": "second section", "page": 2, "section": None},
    ]

    chunks = chunk_sections(sections)

    assert [c["chunk_index"] for c in chunks] == [0, 1]
    assert chunks[0]["page"] == 1
    assert chunks[1]["page"] == 2


def test_split_prefers_paragraph_boundary_over_mid_word_cut():
    text = ("A" * 30) + "\n\n" + ("B" * 30)

    chunks = chunk_sections(
        [{"content": text, "page": None, "section": None}], max_chars=40, overlap=5
    )

    # The paragraph break sits inside the first 40-char window and should be
    # preferred over slicing mid-run-of-characters.
    assert chunks[0]["content"] == "A" * 30
    assert not chunks[0]["content"].endswith("A" * 29 + "\n")


def test_default_max_chars_and_overlap_are_800_and_100():
    text = "x" * 1600
    chunks = chunk_sections([{"content": text, "page": None, "section": None}])

    assert len(chunks) >= 2
    assert all(len(c["content"]) <= 800 for c in chunks)
