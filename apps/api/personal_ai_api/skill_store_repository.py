"""Persistence for the Skill Store API (SPEC.md §6.8 Skill Store, §6.9
supply-chain — manifest/audit snapshots and file hash per version).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Skill, SkillVersion
from personal_ai_api.db import async_session_factory


@dataclass
class SkillRecord:
    id: str
    name: str
    display_name: str
    description: str | None
    current_version: str
    status: str
    installed_at: str
    updated_at: str


@dataclass
class SkillVersionRecord:
    id: str
    version: str
    manifest_snapshot: dict
    audit_report: dict
    file_hash: str
    store_path: str
    created_at: str


class SkillStoreNotFound(Exception):
    pass


class SkillStoreRepository(Protocol):
    async def get_skill_by_name(self, name: str) -> SkillRecord | None: ...

    async def install_or_update_version(
        self,
        name: str,
        display_name: str,
        description: str | None,
        version: str,
        manifest_snapshot: dict,
        audit_report: dict,
        file_hash: str,
        store_path: str,
    ) -> tuple[SkillRecord, SkillVersionRecord]: ...

    async def list_versions(self, name: str) -> list[SkillVersionRecord]: ...

    async def get_version(self, name: str, version: str) -> SkillVersionRecord: ...

    async def set_current_version(self, name: str, version: str) -> SkillRecord: ...

    async def mark_removed(self, name: str) -> SkillRecord: ...


class SqlAlchemySkillStoreRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_skill_by_name(self, name: str) -> SkillRecord | None:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            return _to_skill_record(skill) if skill is not None else None

    async def install_or_update_version(
        self,
        name: str,
        display_name: str,
        description: str | None,
        version: str,
        manifest_snapshot: dict,
        audit_report: dict,
        file_hash: str,
        store_path: str,
    ) -> tuple[SkillRecord, SkillVersionRecord]:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            if skill is None:
                skill = Skill(
                    name=name,
                    display_name=display_name,
                    description=description,
                    current_version=version,
                    status="active",
                )
                session.add(skill)
                await session.flush()  # assign skill.id before the FK below needs it
            else:
                skill.display_name = display_name
                skill.description = description
                skill.current_version = version
                skill.status = "active"

            skill_version = SkillVersion(
                skill_id=skill.id,
                version=version,
                manifest_snapshot=manifest_snapshot,
                audit_report=audit_report,
                file_hash=file_hash,
                store_path=store_path,
            )
            session.add(skill_version)
            await session.commit()
            await session.refresh(skill)
            await session.refresh(skill_version)
            return _to_skill_record(skill), _to_version_record(skill_version)

    async def list_versions(self, name: str) -> list[SkillVersionRecord]:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            if skill is None:
                raise SkillStoreNotFound(name)
            result = await session.execute(
                select(SkillVersion)
                .where(SkillVersion.skill_id == skill.id)
                .order_by(SkillVersion.created_at.desc())
            )
            return [_to_version_record(v) for v in result.scalars().all()]

    async def get_version(self, name: str, version: str) -> SkillVersionRecord:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            if skill is None:
                raise SkillStoreNotFound(name)
            result = await session.execute(
                select(SkillVersion).where(
                    SkillVersion.skill_id == skill.id, SkillVersion.version == version
                )
            )
            skill_version = result.scalar_one_or_none()
            if skill_version is None:
                raise SkillStoreNotFound(f"{name}@{version}")
            return _to_version_record(skill_version)

    async def set_current_version(self, name: str, version: str) -> SkillRecord:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            if skill is None:
                raise SkillStoreNotFound(name)
            skill.current_version = version
            skill.status = "active"
            await session.commit()
            await session.refresh(skill)
            return _to_skill_record(skill)

    async def mark_removed(self, name: str) -> SkillRecord:
        async with self._session_factory() as session:
            skill = await self._find_skill(session, name)
            if skill is None:
                raise SkillStoreNotFound(name)
            skill.status = "removed"
            await session.commit()
            await session.refresh(skill)
            return _to_skill_record(skill)

    async def _find_skill(self, session, name: str) -> Skill | None:
        result = await session.execute(select(Skill).where(Skill.name == name))
        return result.scalar_one_or_none()


def _to_skill_record(skill: Skill) -> SkillRecord:
    return SkillRecord(
        id=str(skill.id),
        name=skill.name,
        display_name=skill.display_name,
        description=skill.description,
        current_version=skill.current_version,
        status=skill.status,
        installed_at=skill.installed_at.isoformat(),
        updated_at=skill.updated_at.isoformat(),
    )


def _to_version_record(skill_version: SkillVersion) -> SkillVersionRecord:
    return SkillVersionRecord(
        id=str(skill_version.id),
        version=skill_version.version,
        manifest_snapshot=skill_version.manifest_snapshot,
        audit_report=skill_version.audit_report,
        file_hash=skill_version.file_hash,
        store_path=skill_version.store_path,
        created_at=skill_version.created_at.isoformat(),
    )


def get_skill_store_repository() -> SkillStoreRepository:
    return SqlAlchemySkillStoreRepository()
