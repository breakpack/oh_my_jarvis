"""Persistence for the chat API (SPEC.md §15 Chat), behind a small repository
seam so tests can substitute an in-memory fake instead of a real database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import AuditEvent, Conversation, ConversationSummary, Message
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class MessageRecord:
    id: str
    role: str
    content: str
    created_at: str


@dataclass
class ConversationRecord:
    id: str
    project_id: str | None
    created_at: str
    updated_at: str
    preview: str | None


class ConversationNotFound(Exception):
    pass


class ChatRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def get_or_create_conversation(
        self, conversation_id: str | None, user_id: str, project_id: str | None = None
    ) -> str: ...

    async def get_conversation(self, conversation_id: str, user_id: str) -> ConversationRecord: ...

    async def add_message(self, conversation_id: str, role: str, content: str) -> MessageRecord: ...

    async def list_messages(self, conversation_id: str) -> list[MessageRecord]: ...

    async def list_conversations(
        self, user_id: str, project_id: str | None = None
    ) -> list[ConversationRecord]: ...

    async def get_conversation_summary(self, conversation_id: str) -> str | None: ...

    async def upsert_conversation_summary(self, conversation_id: str, summary: str) -> None: ...

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ConversationNotFound(value) from exc


class SqlAlchemyChatRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def get_conversation(self, conversation_id: str, user_id: str) -> ConversationRecord:
        conv_uuid = _parse_uuid(conversation_id)
        async with self._session_factory() as session:
            result = await session.execute(
                select(Conversation).where(
                    Conversation.id == conv_uuid, Conversation.user_id == _parse_uuid(user_id)
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation is None:
                raise ConversationNotFound(conversation_id)
            return _to_record(conversation, preview=None)

    async def get_or_create_conversation(
        self, conversation_id: str | None, user_id: str, project_id: str | None = None
    ) -> str:
        if conversation_id:
            record = await self.get_conversation(conversation_id, user_id)
            return record.id

        async with self._session_factory() as session:
            conversation = Conversation(
                user_id=_parse_uuid(user_id),
                project_id=_parse_uuid(project_id) if project_id else None,
            )
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
            return str(conversation.id)

    async def add_message(self, conversation_id: str, role: str, content: str) -> MessageRecord:
        async with self._session_factory() as session:
            message = Message(
                conversation_id=_parse_uuid(conversation_id), role=role, content=content
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return MessageRecord(
                id=str(message.id),
                role=message.role,
                content=message.content,
                created_at=message.created_at.isoformat(),
            )

    async def list_messages(self, conversation_id: str) -> list[MessageRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == _parse_uuid(conversation_id))
                .order_by(Message.created_at)
            )
            return [
                MessageRecord(
                    id=str(m.id),
                    role=m.role,
                    content=m.content,
                    created_at=m.created_at.isoformat(),
                )
                for m in result.scalars().all()
            ]

    async def list_conversations(
        self, user_id: str, project_id: str | None = None
    ) -> list[ConversationRecord]:
        async with self._session_factory() as session:
            stmt = select(Conversation).where(Conversation.user_id == _parse_uuid(user_id))
            if project_id:
                stmt = stmt.where(Conversation.project_id == _parse_uuid(project_id))
            result = await session.execute(stmt.order_by(Conversation.updated_at.desc()))

            records = []
            for conversation in result.scalars().all():
                preview_result = await session.execute(
                    select(Message.content)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
                records.append(
                    _to_record(conversation, preview=preview_result.scalar_one_or_none())
                )
            return records

    async def get_conversation_summary(self, conversation_id: str) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationSummary.summary).where(
                    ConversationSummary.conversation_id == _parse_uuid(conversation_id)
                )
            )
            return result.scalar_one_or_none()

    async def upsert_conversation_summary(self, conversation_id: str, summary: str) -> None:
        conv_uuid = _parse_uuid(conversation_id)
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationSummary).where(ConversationSummary.conversation_id == conv_uuid)
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                existing.summary = summary
            else:
                session.add(ConversationSummary(conversation_id=conv_uuid, summary=summary))
            await session.commit()

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            session.add(
                AuditEvent(user_id=_parse_uuid(user_id), event_type=event_type, payload=payload)
            )
            await session.commit()


def _to_record(conversation: Conversation, preview: str | None) -> ConversationRecord:
    return ConversationRecord(
        id=str(conversation.id),
        project_id=str(conversation.project_id) if conversation.project_id else None,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        preview=preview,
    )


def get_chat_repository() -> ChatRepository:
    return SqlAlchemyChatRepository()
