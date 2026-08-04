"""Unit tests for personal_ai.knowledge.parsers (SPEC.md §8.6 Parsing,
§3.4 Replaceable Components). The pypdf call is stubbed so this doesn't
need a real PDF fixture file.
"""

from __future__ import annotations

import pytest

from personal_ai.knowledge.parsers import (
    DoclingParser,
    MarkdownParser,
    PdfParser,
    TextParser,
    select_parser,
)


def test_select_parser_picks_pdf_by_extension():
    assert isinstance(select_parser("report.PDF"), PdfParser)


def test_select_parser_picks_markdown_by_extension():
    assert isinstance(select_parser("notes.md"), MarkdownParser)
    assert isinstance(select_parser("notes.markdown"), MarkdownParser)


def test_select_parser_falls_back_to_text_for_unknown_extensions():
    assert isinstance(select_parser("script.py"), TextParser)
    assert isinstance(select_parser("no_extension"), TextParser)


async def test_text_parser_returns_whole_file_as_one_section():
    parser = TextParser()

    result = await parser.parse(b"line one\nline two", "notes.txt")

    assert result["text"] == "line one\nline two"
    assert result["sections"] == [{"content": "line one\nline two", "page": None, "section": None}]


async def test_text_parser_returns_no_sections_for_blank_content():
    parser = TextParser()

    result = await parser.parse(b"   \n  ", "blank.txt")

    assert result["sections"] == []


async def test_text_parser_raises_on_undecodable_bytes():
    parser = TextParser()

    with pytest.raises(ValueError, match="Could not decode"):
        await parser.parse(b"\xff\xfe\x00\x01", "binary.dat")


async def test_pdf_parser_splits_by_page_and_skips_blank_pages(monkeypatch):
    class _FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _FakePdfReader:
        def __init__(self, stream) -> None:
            self.pages = [
                _FakePage("Page one text"),
                _FakePage("   "),
                _FakePage("Page three text"),
            ]

    monkeypatch.setattr("pypdf.PdfReader", _FakePdfReader)

    parser = PdfParser()
    result = await parser.parse(b"fake-pdf-bytes", "doc.pdf")

    assert [s["content"] for s in result["sections"]] == ["Page one text", "Page three text"]
    assert [s["page"] for s in result["sections"]] == [1, 3]
    assert all(s["section"] is None for s in result["sections"])
    assert result["text"] == "Page one text\n\nPage three text"


async def test_docling_parser_raises_not_implemented_with_guidance():
    parser = DoclingParser()

    with pytest.raises(NotImplementedError, match="Docling adapter"):
        await parser.parse(b"", "doc.pdf")
