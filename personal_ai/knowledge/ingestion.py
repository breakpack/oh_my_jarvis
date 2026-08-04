"""Document ingestion pipeline (SPEC.md §8.5: Ingestion → Parse → Chunk →
Embed → Index).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.knowledge.chunker import chunk_sections
from personal_ai.knowledge.embeddings import OllamaEmbeddingProvider
from personal_ai.knowledge.parsers import select_parser
from personal_ai.models.db import Document, DocumentChunk, DocumentEmbedding

logger = logging.getLogger(__name__)

_SOURCE_TYPES_BY_EXTENSION = {"pdf": "pdf", "md": "markdown", "markdown": "markdown"}


def _source_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _SOURCE_TYPES_BY_EXTENSION.get(ext, "text")


async def ingest_document(
    session_factory: async_sessionmaker,
    embedding_provider: OllamaEmbeddingProvider,
    user_id: str,
    project_id: str | None,
    title: str,
    filename: str,
    raw: bytes,
) -> Document:
    async with session_factory() as session:
        document = Document(
            user_id=uuid.UUID(user_id),
            project_id=uuid.UUID(project_id) if project_id else None,
            title=title,
            source_type=_source_type(filename),
            source_path=filename,
            status="processing",
        )
        session.add(document)
        await session.flush()
        document_id = document.id

        try:
            parser = select_parser(filename)
            parsed = await parser.parse(raw, filename)
            chunks = chunk_sections(parsed["sections"])
            if not chunks:
                raise ValueError("No extractable text found in the uploaded document.")

            # One batch embedding call for every chunk, not one call per chunk.
            vectors = await embedding_provider.embed([chunk["content"] for chunk in chunks])

            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk_row = DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    section=chunk["section"],
                    page=chunk["page"],
                )
                session.add(chunk_row)
                await session.flush()
                session.add(DocumentEmbedding(chunk_id=chunk_row.id, embedding=vector))

            document.status = "ready"
            # Everything above is flushed-but-uncommitted until here, so the
            # document + all chunks + all embeddings land in one transaction.
            await session.commit()
            await session.refresh(document)
            return document
        except Exception as exc:
            logger.exception("Document ingestion failed for '%s'", filename)
            await session.rollback()
            ingestion_error = exc

    async with session_factory() as session:
        result = await session.execute(select(Document).where(Document.id == document_id))
        failed_document = result.scalar_one()
        failed_document.status = "failed"
        await session.commit()

    raise ingestion_error
