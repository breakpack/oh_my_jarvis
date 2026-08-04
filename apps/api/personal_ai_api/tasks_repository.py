"""Persistence for the Tasks API (SPEC.md §12.1 LOW_WRITE -- auto-approved,
no approval gate needed)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Task
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class TaskRecord:
    id: str
    project_id: str | None
    title: str
    description: str | None
    status: str
    due_at: str | None
    created_at: str
    updated_at: str


class TaskNotFound(Exception):
    pass


class TasksRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None,
        project_id: str | None,
        due_at: datetime | None,
    ) -> TaskRecord: ...

    async def list_tasks(
        self, user_id: str, project_id: str | None = None, status: str | None = None
    ) -> list[TaskRecord]: ...

    async def update_task(self, task_id: str, user_id: str, updates: dict) -> TaskRecord: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise TaskNotFound(value) from exc


class SqlAlchemyTasksRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None,
        project_id: str | None,
        due_at: datetime | None,
    ) -> TaskRecord:
        async with self._session_factory() as session:
            task = Task(
                user_id=_parse_uuid(user_id),
                project_id=_parse_uuid(project_id) if project_id else None,
                title=title,
                description=description,
                due_at=due_at,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return _to_record(task)

    async def list_tasks(
        self, user_id: str, project_id: str | None = None, status: str | None = None
    ) -> list[TaskRecord]:
        async with self._session_factory() as session:
            stmt = select(Task).where(Task.user_id == _parse_uuid(user_id))
            if project_id:
                stmt = stmt.where(Task.project_id == _parse_uuid(project_id))
            if status:
                stmt = stmt.where(Task.status == status)
            result = await session.execute(stmt.order_by(Task.created_at.desc()))
            return [_to_record(t) for t in result.scalars().all()]

    async def update_task(self, task_id: str, user_id: str, updates: dict) -> TaskRecord:
        async with self._session_factory() as session:
            task = await self._get_owned(session, task_id, user_id)
            for field, value in updates.items():
                setattr(task, field, value)
            await session.commit()
            await session.refresh(task)
            return _to_record(task)

    async def _get_owned(self, session, task_id: str, user_id: str) -> Task:
        result = await session.execute(
            select(Task).where(
                Task.id == _parse_uuid(task_id), Task.user_id == _parse_uuid(user_id)
            )
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise TaskNotFound(task_id)
        return task


def _to_record(task: Task) -> TaskRecord:
    return TaskRecord(
        id=str(task.id),
        project_id=str(task.project_id) if task.project_id else None,
        title=task.title,
        description=task.description,
        status=task.status,
        due_at=task.due_at.isoformat() if task.due_at else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


def get_tasks_repository() -> TasksRepository:
    return SqlAlchemyTasksRepository()
