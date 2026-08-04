"""Document parsers (SPEC.md §8.6 Parsing, §3.4 Replaceable Components).

Docling is intentionally not wired in for this MVP — it pulls in heavy ML
dependencies (torch, ...). `DocumentParser` is a small Protocol so a
`DoclingParser` adapter can be dropped in later (structured PDF/DOCX/PPTX
parsing) without ingestion.py or callers changing at all.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class Section(TypedDict):
    content: str
    page: int | None
    section: str | None


class ParsedDocument(TypedDict):
    text: str
    sections: list[Section]


class DocumentParser(Protocol):
    async def parse(self, raw: bytes, filename: str) -> ParsedDocument: ...


class PdfParser:
    """Page-by-page text extraction via pypdf — no layout/table structure,
    no OCR for scanned pages (SPEC §8.6 fallback path)."""

    async def parse(self, raw: bytes, filename: str) -> ParsedDocument:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        sections: list[Section] = []
        for page_number, page in enumerate(reader.pages, start=1):
            content = (page.extract_text() or "").strip()
            if content:
                sections.append({"content": content, "page": page_number, "section": None})
        return {"text": "\n\n".join(s["content"] for s in sections), "sections": sections}


class TextParser:
    """Plain-text/Markdown/code: the whole file is a single section."""

    async def parse(self, raw: bytes, filename: str) -> ParsedDocument:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Could not decode '{filename}' as UTF-8 text.") from exc

        text = text.strip()
        sections: list[Section] = [{"content": text, "page": None, "section": None}] if text else []
        return {"text": text, "sections": sections}


# Markdown and source code get no special structure extraction yet — same
# whole-file-as-one-section handling as plain text.
MarkdownParser = TextParser
CodeParser = TextParser


class DoclingParser:
    """Adapter slot for Docling (SPEC.md §5.2) — not installed in this MVP."""

    async def parse(self, raw: bytes, filename: str) -> ParsedDocument:
        raise NotImplementedError(
            "Docling adapter — see SPEC.md §5.2, install `docling` and implement to enable"
        )


_PARSERS_BY_EXTENSION: dict[str, type[DocumentParser]] = {
    ".pdf": PdfParser,
    ".md": MarkdownParser,
    ".markdown": MarkdownParser,
}


def select_parser(filename: str) -> DocumentParser:
    """Pick a parser by file extension; anything unrecognized falls back to
    plain-text decoding (which raises if the bytes aren't valid UTF-8)."""
    parser_cls = _PARSERS_BY_EXTENSION.get(_extension(filename), TextParser)
    return parser_cls()


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot != -1 else ""
