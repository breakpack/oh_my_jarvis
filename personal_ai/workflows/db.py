"""Async engine for the tool_executions dedup ledger
(personal_ai.models.db.ToolExecution; SPEC.md §25 DoD "중복 Tool 실행
방지"). Reads DATABASE_URL from the environment directly, same convention
as personal_ai.workflows.checkpointer.

A fresh engine (and connection pool) is built on every call rather than
cached at module scope — same tradeoff as
personal_ai.workflows.checkpointer.get_checkpointer(), and for the same
two reasons: it's what lets every workflow run genuinely not depend on
any prior in-process state, and an async engine cached across calls would
otherwise end up bound to whichever asyncio event loop was running the
first time it was built (a real problem in tests, where each test
function gets its own event loop — discovered the hard way).
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_ai"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
