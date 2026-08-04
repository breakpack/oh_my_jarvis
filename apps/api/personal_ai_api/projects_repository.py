"""Persistence for the Projects API (SPEC.md §15 Projects)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Project
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class ProjectRecord:
    id: str
    name: str
    description: str | None
    status: str
    created_at: str
    updated_at: str


class ProjectNotFound(Exception):
    pass


class ProjectsRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def create_project(
        self, user_id: str, name: str, description: str | None
    ) -> ProjectRecord: ...

    async def list_projects(self, user_id: str) -> list[ProjectRecord]: ...

    async def get_project(self, project_id: str, user_id: str) -> ProjectRecord: ...

    async def update_project(
        self, project_id: str, user_id: str, updates: dict
    ) -> ProjectRecord: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ProjectNotFound(value) from exc


class SqlAlchemyProjectsRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def create_project(
        self, user_id: str, name: str, description: str | None
    ) -> ProjectRecord:
        async with self._session_factory() as session:
            project = Project(user_id=_parse_uuid(user_id), name=name, description=description)
            session.add(project)
            await session.commit()
            await session.refresh(project)
            return _to_record(project)

    async def list_projects(self, user_id: str) -> list[ProjectRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(Project)
                .where(Project.user_id == _parse_uuid(user_id))
                .order_by(Project.created_at.desc())
            )
            return [_to_record(p) for p in result.scalars().all()]

    async def get_project(self, project_id: str, user_id: str) -> ProjectRecord:
        async with self._session_factory() as session:
            project = await self._get_owned(session, project_id, user_id)
            return _to_record(project)

    async def update_project(self, project_id: str, user_id: str, updates: dict) -> ProjectRecord:
        async with self._session_factory() as session:
            project = await self._get_owned(session, project_id, user_id)
            for field, value in updates.items():
                setattr(project, field, value)
            await session.commit()
            await session.refresh(project)
            return _to_record(project)

    async def _get_owned(self, session, project_id: str, user_id: str) -> Project:
        result = await session.execute(
            select(Project).where(
                Project.id == _parse_uuid(project_id), Project.user_id == _parse_uuid(user_id)
            )
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise ProjectNotFound(project_id)
        return project


def _to_record(project: Project) -> ProjectRecord:
    return ProjectRecord(
        id=str(project.id),
        name=project.name,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


def get_projects_repository() -> ProjectsRepository:
    return SqlAlchemyProjectsRepository()
