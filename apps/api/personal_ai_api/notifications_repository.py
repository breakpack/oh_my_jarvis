"""Persistence for the Notifications API (SPEC.md §13, §15).

CRUD only (list/seen/dismiss) -- creating notifications is
proactive_scheduler.py's job, since run_check_cycle()'s specified return
type is real Notification ORM rows, not the Record dataclass this
repository's read path returns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Notification
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class NotificationRecord:
    id: str
    source_type: str
    title: str
    body: str
    priority: str
    status: str
    created_at: str
    updated_at: str


class NotificationNotFound(Exception):
    pass


class NotificationsRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def list_notifications(
        self, user_id: str, status: str | None
    ) -> list[NotificationRecord]: ...

    async def update_notification(
        self, notification_id: str, user_id: str, updates: dict
    ) -> NotificationRecord: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise NotificationNotFound(value) from exc


class SqlAlchemyNotificationsRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def list_notifications(
        self, user_id: str, status: str | None
    ) -> list[NotificationRecord]:
        async with self._session_factory() as session:
            stmt = select(Notification).where(Notification.user_id == _parse_uuid(user_id))
            if status:
                stmt = stmt.where(Notification.status == status)
            result = await session.execute(stmt.order_by(Notification.created_at.desc()))
            return [_to_record(n) for n in result.scalars().all()]

    async def update_notification(
        self, notification_id: str, user_id: str, updates: dict
    ) -> NotificationRecord:
        async with self._session_factory() as session:
            notification = await self._get_owned(session, notification_id, user_id)
            for field, value in updates.items():
                setattr(notification, field, value)
            await session.commit()
            await session.refresh(notification)
            return _to_record(notification)

    async def _get_owned(self, session, notification_id: str, user_id: str) -> Notification:
        result = await session.execute(
            select(Notification).where(
                Notification.id == _parse_uuid(notification_id),
                Notification.user_id == _parse_uuid(user_id),
            )
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            raise NotificationNotFound(notification_id)
        return notification


def _to_record(notification: Notification) -> NotificationRecord:
    return NotificationRecord(
        id=str(notification.id),
        source_type=notification.source_type,
        title=notification.title,
        body=notification.body,
        priority=notification.priority,
        status=notification.status,
        created_at=notification.created_at.isoformat(),
        updated_at=notification.updated_at.isoformat(),
    )


def get_notifications_repository() -> NotificationsRepository:
    return SqlAlchemyNotificationsRepository()
