"""Shared async DB plumbing for repositories (SPEC.md §14).

Every repository in this phase operates as a single local user until auth
lands (SPEC.md Phase 5+), so the "get or create the default user" lookup
and the engine/session factory live here once instead of being redefined
per repository module.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from personal_ai.models.db import User
from personal_ai_api.config import settings

DEFAULT_USER_EMAIL = "local@personal-ai.local"

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_or_create_default_user(
    session_factory: async_sessionmaker = async_session_factory,
) -> str:
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == DEFAULT_USER_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(email=DEFAULT_USER_EMAIL, display_name="Local User")
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return str(user.id)


async def get_default_user_id() -> str:
    """No-arg wrapper so this can be used directly as a FastAPI `Depends`
    target (and overridden in tests) — `get_or_create_default_user` itself
    takes a `session_factory` param that FastAPI would otherwise try to
    resolve as a request parameter."""
    return await get_or_create_default_user()
