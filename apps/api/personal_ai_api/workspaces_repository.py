"""Persistence for the Workspaces API (SPEC.md §9 Development Mode).

This is metadata/history only (which workspace exists, its status, the
commands run in it) -- the actual sandboxed git worktree lives on disk and
is owned by personal_ai.development.workspace.GitWorktreeRuntime, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Workspace, WorkspaceRun
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class WorkspaceRecord:
    id: str
    source_path: str
    workspace_dir: str
    status: str
    created_at: str
    updated_at: str


class WorkspaceRecordNotFound(Exception):
    """A Workspace DB row doesn't exist for the given id -- distinct from
    personal_ai.development.workspace.WorkspaceNotFound, which means the
    on-disk worktree directory is missing even though the DB row exists
    (e.g. a destroyed workspace)."""


class WorkspacesRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def create_workspace(
        self, user_id: str, workspace_id: str, source_path: str, workspace_dir: str
    ) -> WorkspaceRecord: ...

    async def get_workspace(self, workspace_id: str, user_id: str) -> WorkspaceRecord: ...

    async def update_workspace(
        self, workspace_id: str, user_id: str, updates: dict
    ) -> WorkspaceRecord: ...

    async def record_run(
        self,
        workspace_id: str,
        command: list[str],
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> None: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise WorkspaceRecordNotFound(value) from exc


class SqlAlchemyWorkspacesRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def create_workspace(
        self, user_id: str, workspace_id: str, source_path: str, workspace_dir: str
    ) -> WorkspaceRecord:
        async with self._session_factory() as session:
            # The DB row's id must equal the runtime's workspace_id (the
            # directory name GitWorktreeRuntime actually created) -- every
            # later call (run/diff/search/...) is keyed by this id, so a
            # mismatch here would silently point at a directory that
            # doesn't exist.
            workspace = Workspace(
                id=_parse_uuid(workspace_id),
                user_id=_parse_uuid(user_id),
                source_path=source_path,
                workspace_dir=workspace_dir,
            )
            session.add(workspace)
            await session.commit()
            await session.refresh(workspace)
            return _to_record(workspace)

    async def get_workspace(self, workspace_id: str, user_id: str) -> WorkspaceRecord:
        async with self._session_factory() as session:
            workspace = await self._get_owned(session, workspace_id, user_id)
            return _to_record(workspace)

    async def update_workspace(
        self, workspace_id: str, user_id: str, updates: dict
    ) -> WorkspaceRecord:
        async with self._session_factory() as session:
            workspace = await self._get_owned(session, workspace_id, user_id)
            for field, value in updates.items():
                setattr(workspace, field, value)
            await session.commit()
            await session.refresh(workspace)
            return _to_record(workspace)

    async def record_run(
        self,
        workspace_id: str,
        command: list[str],
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                WorkspaceRun(
                    workspace_id=_parse_uuid(workspace_id),
                    command=command,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()

    async def _get_owned(self, session, workspace_id: str, user_id: str) -> Workspace:
        result = await session.execute(
            select(Workspace).where(
                Workspace.id == _parse_uuid(workspace_id),
                Workspace.user_id == _parse_uuid(user_id),
            )
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise WorkspaceRecordNotFound(workspace_id)
        return workspace


def _to_record(workspace: Workspace) -> WorkspaceRecord:
    return WorkspaceRecord(
        id=str(workspace.id),
        source_path=workspace.source_path,
        workspace_dir=workspace.workspace_dir,
        status=workspace.status,
        created_at=workspace.created_at.isoformat(),
        updated_at=workspace.updated_at.isoformat(),
    )


def get_workspaces_repository() -> WorkspacesRepository:
    return SqlAlchemyWorkspacesRepository()
