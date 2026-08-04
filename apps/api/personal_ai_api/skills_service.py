"""Service layer for the Skills API (SPEC.md §6.5 lifecycle, §6.6 resolver,
§20.4 audit).

Skills are discovered once from the repo-root `skills/` directory and kept
in an in-memory cache for the life of the process, along with an `enabled`
set (defaulting to "every discovered skill"). SPEC scopes persisted
enable/disable state to Phase 10's Skill Store, so there is no DB table
here — a server restart resetting back to "all discovered skills enabled"
is the correct behavior for this phase.
ponytail: no filesystem watch / hot-reload — skills/ changes require a
restart until Phase 10.
"""

from __future__ import annotations

import importlib.util
import inspect
import uuid
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import AuditEvent
from personal_ai.skills.registry import LoadedSkill, SkillRegistry
from personal_ai.skills.resolver import SkillResolver
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"

DEFAULT_RESOLVE_TOP_K = 3
DEFAULT_AUDIT_LIMIT = 20


class SkillNotFound(Exception):
    pass


class _DiscoveryCache:
    """Lazy, process-lifetime cache around `SkillRegistry.discover()`."""

    def __init__(self) -> None:
        self._skills: list[LoadedSkill] | None = None
        self._errors: list[tuple[str, str]] = []
        self.enabled: set[str] = set()

    def _ensure_loaded(self) -> None:
        if self._skills is not None:
            return
        registry = SkillRegistry()
        self._skills = registry.discover(SKILLS_DIR)
        self._errors = registry.errors
        self.enabled = {skill.name for skill in self._skills}

    @property
    def skills(self) -> list[LoadedSkill]:
        self._ensure_loaded()
        assert self._skills is not None
        return self._skills

    @property
    def errors(self) -> list[tuple[str, str]]:
        self._ensure_loaded()
        return self._errors


_cache = _DiscoveryCache()


def reset_cache() -> None:
    """Test-only escape hatch: force the next lookup to re-discover, so
    enable/disable state from one test doesn't leak into the next."""
    global _cache
    _cache = _DiscoveryCache()


def list_skills(
    query: str | None = None, top_k: int = DEFAULT_RESOLVE_TOP_K
) -> tuple[list[LoadedSkill], list[tuple[str, str]]]:
    skills = _cache.skills
    if query:
        skills = SkillResolver().resolve(skills, query, top_k=top_k)
    return skills, _cache.errors


def get_skill(name: str) -> LoadedSkill:
    for skill in _cache.skills:
        if skill.name == name:
            return skill
    raise SkillNotFound(name)


def is_enabled(name: str) -> bool:
    return name in _cache.enabled


def set_enabled(name: str, enabled: bool) -> None:
    get_skill(name)  # raises SkillNotFound if the name isn't a real skill
    if enabled:
        _cache.enabled.add(name)
    else:
        _cache.enabled.discard(name)


def find_skill_class(loaded: LoadedSkill) -> type | None:
    """Dynamically import skills/<name>/workflow.py and return the Skill
    class it defines, or None if there is no workflow.py (a Stub skill).

    Workflow classes don't populate their `manifest` class attribute (it's
    left as `{}` — see github-issues-lookup/workflow.py), so matching by
    manifest name isn't possible; the first class defined in the module
    that duck-types the Skill protocol (has plan/execute/verify) is used.
    """
    workflow_path = Path(loaded.path) / "workflow.py"
    if not workflow_path.is_file():
        return None

    module_name = f"personal_ai_api._skill_workflows.{loaded.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, workflow_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            obj.__module__ == module.__name__
            and hasattr(obj, "plan")
            and hasattr(obj, "execute")
            and hasattr(obj, "verify")
        ):
            return obj
    return None


def _parse_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


class SkillsRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None: ...

    async def list_skill_audit(
        self, skill_name: str, limit: int = DEFAULT_AUDIT_LIMIT
    ) -> list[dict]: ...


class SqlAlchemySkillsRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            session.add(
                AuditEvent(user_id=_parse_uuid(user_id), event_type=event_type, payload=payload)
            )
            await session.commit()

    async def list_skill_audit(
        self, skill_name: str, limit: int = DEFAULT_AUDIT_LIMIT
    ) -> list[dict]:
        async with self._session_factory() as session:
            stmt = (
                select(AuditEvent)
                .where(
                    AuditEvent.event_type == "skill_run",
                    AuditEvent.payload["skill"].astext == skill_name,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
                for event in result.scalars().all()
            ]


def get_skills_repository() -> SkillsRepository:
    return SqlAlchemySkillsRepository()
