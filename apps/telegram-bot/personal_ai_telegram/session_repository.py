"""Per-chat session state (SPEC.md: chat_id -> active conversation/project),
persisted so the bot process can restart without losing context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_ai.models.db import TelegramSession
from personal_ai_telegram.config import Settings

settings = Settings()  # type: ignore[call-arg]  # values come from .env, not kwargs
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@dataclass
class SessionRecord:
    chat_id: str
    conversation_id: str | None
    project_id: str | None
    last_notification_check_at: datetime | None


def _to_record(row: TelegramSession) -> SessionRecord:
    return SessionRecord(
        chat_id=row.chat_id,
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
        project_id=str(row.project_id) if row.project_id else None,
        last_notification_check_at=row.last_notification_check_at,
    )


class SessionRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create(self, chat_id: str) -> SessionRecord:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramSession).where(TelegramSession.chat_id == chat_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = TelegramSession(chat_id=chat_id)
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return _to_record(row)

    async def set_conversation(self, chat_id: str, conversation_id: str | None) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramSession).where(TelegramSession.chat_id == chat_id)
            )
            row = result.scalar_one()
            row.conversation_id = uuid.UUID(conversation_id) if conversation_id else None
            await session.commit()

    async def set_project(self, chat_id: str, project_id: str | None) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramSession).where(TelegramSession.chat_id == chat_id)
            )
            row = result.scalar_one()
            row.project_id = uuid.UUID(project_id) if project_id else None
            await session.commit()

    async def advance_notification_watermark(self, chat_id: str, now: datetime) -> datetime | None:
        """Returns the previous watermark (to filter notifications created
        after it) and moves it forward to `now`."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(TelegramSession).where(TelegramSession.chat_id == chat_id)
            )
            row = result.scalar_one()
            previous = row.last_notification_check_at
            row.last_notification_check_at = now
            await session.commit()
            return previous


default_session_repository = SessionRepository()
