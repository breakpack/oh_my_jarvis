"""Persistence for the Memory API (SPEC.md §8 Memory, §15 Memory).

No embedding/vector search yet (Phase 3 adds it) — retrieval is a simple
ILIKE content match, matching personal_ai/models/db.py's Memory model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Memory
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class MemoryRecord:
    id: str
    project_id: str | None
    content: str
    source: str
    confidence: float
    valid_from: str | None
    valid_until: str | None
    created_at: str
    updated_at: str


class MemoryNotFound(Exception):
    pass


class MemoryRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def create_memory(
        self,
        user_id: str,
        content: str,
        project_id: str | None,
        source: str,
        confidence: float,
        valid_until: datetime | None,
    ) -> MemoryRecord: ...

    async def list_memories(
        self, user_id: str, project_id: str | None = None, query: str | None = None
    ) -> list[MemoryRecord]: ...

    async def update_memory(self, memory_id: str, user_id: str, updates: dict) -> MemoryRecord: ...

    async def delete_memory(self, memory_id: str, user_id: str) -> None: ...

    async def delete_memories_by_content(
        self, user_id: str, project_id: str | None, query: str
    ) -> int: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise MemoryNotFound(value) from exc


class SqlAlchemyMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def create_memory(
        self,
        user_id: str,
        content: str,
        project_id: str | None,
        source: str,
        confidence: float,
        valid_until: datetime | None,
    ) -> MemoryRecord:
        async with self._session_factory() as session:
            memory = Memory(
                user_id=_parse_uuid(user_id),
                project_id=_parse_uuid(project_id) if project_id else None,
                content=content,
                source=source,
                confidence=confidence,
                valid_until=valid_until,
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            return _to_record(memory)

    async def list_memories(
        self, user_id: str, project_id: str | None = None, query: str | None = None
    ) -> list[MemoryRecord]:
        async with self._session_factory() as session:
            stmt = select(Memory).where(Memory.user_id == _parse_uuid(user_id))
            if project_id:
                stmt = stmt.where(Memory.project_id == _parse_uuid(project_id))
            if query:
                stmt = stmt.where(Memory.content.ilike(f"%{query}%"))
            result = await session.execute(stmt.order_by(Memory.created_at.desc()))
            return [_to_record(m) for m in result.scalars().all()]

    async def update_memory(self, memory_id: str, user_id: str, updates: dict) -> MemoryRecord:
        async with self._session_factory() as session:
            memory = await self._get_owned(session, memory_id, user_id)
            for field, value in updates.items():
                setattr(memory, field, value)
            await session.commit()
            await session.refresh(memory)
            return _to_record(memory)

    async def delete_memory(self, memory_id: str, user_id: str) -> None:
        async with self._session_factory() as session:
            memory = await self._get_owned(session, memory_id, user_id)
            await session.delete(memory)
            await session.commit()

    async def delete_memories_by_content(
        self, user_id: str, project_id: str | None, query: str
    ) -> int:
        async with self._session_factory() as session:
            stmt = select(Memory).where(
                Memory.user_id == _parse_uuid(user_id), Memory.content.ilike(f"%{query}%")
            )
            if project_id:
                stmt = stmt.where(Memory.project_id == _parse_uuid(project_id))
            result = await session.execute(stmt)
            memories = result.scalars().all()
            for memory in memories:
                await session.delete(memory)
            await session.commit()
            return len(memories)

    async def _get_owned(self, session, memory_id: str, user_id: str) -> Memory:
        result = await session.execute(
            select(Memory).where(
                Memory.id == _parse_uuid(memory_id), Memory.user_id == _parse_uuid(user_id)
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            raise MemoryNotFound(memory_id)
        return memory


def _to_record(memory: Memory) -> MemoryRecord:
    return MemoryRecord(
        id=str(memory.id),
        project_id=str(memory.project_id) if memory.project_id else None,
        content=memory.content,
        source=memory.source,
        confidence=memory.confidence,
        valid_from=memory.valid_from.isoformat() if memory.valid_from else None,
        valid_until=memory.valid_until.isoformat() if memory.valid_until else None,
        created_at=memory.created_at.isoformat(),
        updated_at=memory.updated_at.isoformat(),
    )


def get_memory_repository() -> MemoryRepository:
    return SqlAlchemyMemoryRepository()
