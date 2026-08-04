"""Postgres-backed LangGraph checkpointer (SPEC.md §5.2, §25 DoD "서버
재시작 후 복구"). Every checkpoint LangGraph writes for a graph run lands
in Postgres via this saver, which is exactly what lets a brand-new process
resume a paused workflow from nothing but a thread_id.
"""

from __future__ import annotations

import os

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

_DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_ai"

# `from_conn_string` is an @asynccontextmanager: entering it manually via
# __aenter__() without holding a reference to the context-manager object
# lets it get garbage-collected, which tears down its connection pool out
# from under the returned saver (discovered the hard way — every query
# after that started failing with "the connection is closed"). Keeping
# every one of these alive for the process lifetime is the other half of
# this module's documented "never explicitly closed" tradeoff.
_open_saver_contexts: list[object] = []


def _psycopg_dsn() -> str:
    """personal_ai core modules read DATABASE_URL from the environment
    directly (same convention as personal_ai.development.workspace)
    rather than importing apps/api's typed Settings, to avoid a backwards
    app-layer -> core-layer dependency. asyncpg's driver suffix isn't a
    psycopg driver name, so it's stripped for psycopg's own DSN."""
    database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


async def get_checkpointer() -> AsyncPostgresSaver:
    """Open a fresh AsyncPostgresSaver (its own connection pool) and
    ensure the checkpoint tables exist (`.setup()` is idempotent — a
    no-op if they're already there).

    ponytail: the returned saver's connection pool is never explicitly
    closed here — `from_conn_string` is itself an async context manager,
    so a long-lived server would want to keep one instance around and
    close it on shutdown instead of opening a new pool per call. Add a
    process-lifetime cache if per-call pool churn becomes a measured
    problem; for now every run_skill_workflow/resume_skill_workflow call
    getting a genuinely fresh saver is also exactly what lets
    resume_skill_workflow prove it works without any in-process state.
    """
    dsn = _psycopg_dsn()
    saver_cm = AsyncPostgresSaver.from_conn_string(dsn)
    saver = await saver_cm.__aenter__()
    _open_saver_contexts.append(saver_cm)
    await saver.setup()
    return saver
