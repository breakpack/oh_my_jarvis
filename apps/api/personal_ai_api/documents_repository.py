"""Persistence + ingestion orchestration for the Documents API
(SPEC.md §15 Knowledge, §8.5)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.knowledge.embeddings import OllamaEmbeddingProvider
from personal_ai.knowledge.ingestion import ingest_document
from personal_ai.models.db import Document, DocumentChunk
from personal_ai_api.config import settings
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class DocumentRecord:
    id: str
    title: str
    source_type: str
    project_id: str | None
    status: str
    chunk_count: int
    created_at: str


class DocumentNotFound(Exception):
    pass


class DocumentsRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def ingest(
        self, user_id: str, project_id: str | None, title: str, filename: str, raw: bytes
    ) -> DocumentRecord: ...

    async def list_documents(
        self, user_id: str, project_id: str | None = None
    ) -> list[DocumentRecord]: ...

    async def get_document(self, document_id: str, user_id: str) -> DocumentRecord: ...

    async def delete_document(self, document_id: str, user_id: str) -> None: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise DocumentNotFound(value) from exc


def get_embedding_provider() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_embedding_model,
        keep_alive=settings.ollama_keep_alive,
    )


class SqlAlchemyDocumentsRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker = async_session_factory,
        embedding_provider: OllamaEmbeddingProvider | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider or get_embedding_provider()

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def ingest(
        self, user_id: str, project_id: str | None, title: str, filename: str, raw: bytes
    ) -> DocumentRecord:
        document = await ingest_document(
            self._session_factory,
            self._embedding_provider,
            user_id=user_id,
            project_id=project_id,
            title=title,
            filename=filename,
            raw=raw,
        )
        return await self.get_document(str(document.id), user_id)

    async def list_documents(
        self, user_id: str, project_id: str | None = None
    ) -> list[DocumentRecord]:
        async with self._session_factory() as session:
            stmt = select(Document).where(Document.user_id == _parse_uuid(user_id))
            if project_id:
                stmt = stmt.where(Document.project_id == _parse_uuid(project_id))
            result = await session.execute(stmt.order_by(Document.created_at.desc()))
            documents = result.scalars().all()
            return [await self._to_record(session, d) for d in documents]

    async def get_document(self, document_id: str, user_id: str) -> DocumentRecord:
        async with self._session_factory() as session:
            document = await self._get_owned(session, document_id, user_id)
            return await self._to_record(session, document)

    async def delete_document(self, document_id: str, user_id: str) -> None:
        async with self._session_factory() as session:
            document = await self._get_owned(session, document_id, user_id)
            # document_chunks/document_embeddings cascade via FK ondelete=CASCADE.
            await session.delete(document)
            await session.commit()

    async def _get_owned(self, session, document_id: str, user_id: str) -> Document:
        result = await session.execute(
            select(Document).where(
                Document.id == _parse_uuid(document_id), Document.user_id == _parse_uuid(user_id)
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise DocumentNotFound(document_id)
        return document

    async def _to_record(self, session, document: Document) -> DocumentRecord:
        count_result = await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
        )
        return DocumentRecord(
            id=str(document.id),
            title=document.title,
            source_type=document.source_type,
            project_id=str(document.project_id) if document.project_id else None,
            status=document.status,
            chunk_count=count_result.scalar_one(),
            created_at=document.created_at.isoformat(),
        )


def get_documents_repository() -> DocumentsRepository:
    return SqlAlchemyDocumentsRepository()
