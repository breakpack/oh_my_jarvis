"""Hybrid (vector + full-text) retrieval over document chunks
(SPEC.md §8.5 Retrieve stage, §8.7 Evidence model)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.knowledge.embeddings import OllamaEmbeddingProvider
from personal_ai.models.db import Document, DocumentChunk, DocumentEmbedding
from personal_ai_api.db import async_session_factory
from personal_ai_api.documents_repository import get_embedding_provider


@dataclass
class SearchResult:
    document_id: str
    document_title: str
    chunk_id: str
    content: str
    page: int | None
    section: str | None
    score: float


class KnowledgeRepository(Protocol):
    async def search(
        self, user_id: str, query: str, project_id: str | None = None, top_k: int = 5
    ) -> list[SearchResult]: ...


class SqlAlchemyKnowledgeRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker = async_session_factory,
        embedding_provider: OllamaEmbeddingProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider or get_embedding_provider()

    async def search(
        self, user_id: str, query: str, project_id: str | None = None, top_k: int = 5
    ) -> list[SearchResult]:
        user_uuid = uuid.UUID(user_id)
        project_uuid = uuid.UUID(project_id) if project_id else None

        async with self._session_factory() as session:
            vector_results = await self._vector_search(
                session, user_uuid, project_uuid, query, top_k
            )
            text_results = await self._text_search(session, user_uuid, project_uuid, query, top_k)

        # Vector matches win on dedup — a text-only match for the same chunk
        # is redundant once the (higher-fidelity) vector score is already in.
        merged: dict[str, SearchResult] = {}
        for result in vector_results:
            merged[result.chunk_id] = result
        for result in text_results:
            merged.setdefault(result.chunk_id, result)
        return list(merged.values())

    async def _vector_search(
        self, session, user_id: uuid.UUID, project_id: uuid.UUID | None, query: str, top_k: int
    ) -> list[SearchResult]:
        try:
            [query_vector] = await self._embedding_provider.embed([query])
        except Exception:
            # Embedding the query failed (e.g. Ollama down) — fall back to
            # text-only results instead of failing the whole search.
            return []

        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.page,
                DocumentChunk.section,
                Document.id.label("document_id"),
                Document.title.label("document_title"),
                DocumentEmbedding.embedding.cosine_distance(query_vector).label("distance"),
            )
            .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.user_id == user_id)
        )
        if project_id:
            stmt = stmt.where(Document.project_id == project_id)
        stmt = stmt.order_by("distance").limit(top_k)

        rows = (await session.execute(stmt)).all()
        return [
            SearchResult(
                document_id=str(row.document_id),
                document_title=row.document_title,
                chunk_id=str(row.id),
                content=row.content,
                page=row.page,
                section=row.section,
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]

    async def _text_search(
        self, session, user_id: uuid.UUID, project_id: uuid.UUID | None, query: str, top_k: int
    ) -> list[SearchResult]:
        stmt = (
            select(
                DocumentChunk.id,
                DocumentChunk.content,
                DocumentChunk.page,
                DocumentChunk.section,
                Document.id.label("document_id"),
                Document.title.label("document_title"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.user_id == user_id,
                text(
                    "to_tsvector('simple', document_chunks.content) "
                    "@@ plainto_tsquery('simple', :fts_query)"
                ),
            )
            .params(fts_query=query)
        )
        if project_id:
            stmt = stmt.where(Document.project_id == project_id)
        stmt = stmt.limit(top_k)

        rows = (await session.execute(stmt)).all()
        return [
            SearchResult(
                document_id=str(row.document_id),
                document_title=row.document_title,
                chunk_id=str(row.id),
                content=row.content,
                page=row.page,
                section=row.section,
                score=0.0,
            )
            for row in rows
        ]


def get_knowledge_repository() -> KnowledgeRepository:
    return SqlAlchemyKnowledgeRepository()
