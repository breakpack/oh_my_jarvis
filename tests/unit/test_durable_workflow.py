"""Durable Skill workflow tests (SPEC.md §25 DoD "서버 재시작 후 복구",
"승인 대기 유지", "중복 Tool 실행 방지"). Requires a live Postgres —
skips cleanly (never errors the rest of the suite) if DATABASE_URL is
missing or unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

from personal_ai.skills.sdk import SkillContext, SkillResult  # noqa: E402
from personal_ai.tools.base import ToolResult  # noqa: E402
from personal_ai.tools.github_write import GithubCreateIssueTool  # noqa: E402
from personal_ai.workflows.skill_run_graph import (  # noqa: E402
    execute_skill_with_dedup,
    resume_skill_workflow,
    run_skill_workflow,
)


def _asyncpg_dsn() -> str | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def require_postgres() -> None:
    dsn = _asyncpg_dsn()
    if dsn is None:
        pytest.skip("requires live Postgres: DATABASE_URL not set")
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5)
    except Exception as exc:
        pytest.skip(f"requires live Postgres: {exc}")
    await conn.close()


async def test_medium_risk_skill_pauses_then_resumes_from_a_fresh_instance(
    require_postgres, monkeypatch
):
    calls: list[dict] = []

    async def fake_execute(self, arguments, context):
        calls.append(arguments)
        return ToolResult(
            success=True,
            data={"number": 99, "url": "https://github.com/x/y/issues/99"},
            evidence=[],
        )

    monkeypatch.setattr(GithubCreateIssueTool, "execute", fake_execute)

    started = await run_skill_workflow(
        "github-issue-create", {"repo": "x/y", "title": "durable test"}, "user-1"
    )
    assert started["status"] == "pending_approval"
    assert started["interrupt"]["reason"] == "approval_required"
    assert started["interrupt"]["skill"] == "github-issue-create"
    thread_id = started["thread_id"]

    # run_skill_workflow/resume_skill_workflow never cache a checkpointer
    # or compiled graph anywhere at module scope — every call opens its own
    # fresh AsyncPostgresSaver connection pool (get_checkpointer()) and
    # compiles its own StateGraph (_build_graph()). This resume call has
    # nothing to work with except `thread_id` and Postgres, exactly what a
    # brand-new process after a server restart would have.
    finished = await resume_skill_workflow(thread_id, "approve")
    assert finished["status"] == "completed"
    assert finished["result"]["success"] is True
    assert finished["result"]["data"]["number"] == 99
    assert len(calls) == 1


async def test_reject_decision_marks_the_run_failed_without_executing(
    require_postgres, monkeypatch
):
    calls: list[dict] = []

    async def fake_execute(self, arguments, context):
        calls.append(arguments)
        return ToolResult(success=True, data={"number": 1, "url": "u"}, evidence=[])

    monkeypatch.setattr(GithubCreateIssueTool, "execute", fake_execute)

    started = await run_skill_workflow(
        "github-issue-create", {"repo": "x/y", "title": "should be rejected"}, "user-1"
    )
    thread_id = started["thread_id"]

    finished = await resume_skill_workflow(thread_id, "reject")

    assert finished["status"] == "completed"
    assert finished["result"]["success"] is False
    assert "reject" in finished["result"]["error"].lower()
    assert calls == []  # a rejected run must never call skill.execute()


async def test_read_level_skill_completes_without_interrupt(
    require_postgres, tmp_path, monkeypatch
):
    (tmp_path / "notes.txt").write_text("hello world TODO", encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    result = await run_skill_workflow("local-file-search", {"query": "TODO"}, "user-1")

    assert result["status"] == "completed"
    assert result["result"]["success"] is True


async def test_execute_skill_with_dedup_only_calls_skill_execute_once(require_postgres):
    # Exercises the "execute" node's actual logic directly, twice, with
    # the same thread_id/tool_name/arguments — the scenario SPEC's DoD
    # "중복 Tool 실행 방지" describes, verified against the real
    # tool_executions table rather than through a full graph resume (whose
    # "resume an already-completed thread" behavior is a LangGraph
    # implementation detail this test shouldn't depend on).
    thread_id = str(uuid.uuid4())
    context = SkillContext(
        user_id="user-1",
        conversation_id="conv-1",
        project_id=None,
        workspace_id=None,
        local_only=False,
        granted_scopes=set(),
    )
    arguments = {"foo": "bar"}
    call_count = 0

    class FakeSkill:
        async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
            nonlocal call_count
            call_count += 1
            return SkillResult(success=True, summary="ran", data={"call_number": call_count})

    skill = FakeSkill()

    result1 = await execute_skill_with_dedup(thread_id, "fake.tool", arguments, context, skill)
    result2 = await execute_skill_with_dedup(thread_id, "fake.tool", arguments, context, skill)

    assert call_count == 1
    assert result1 == result2
    assert result1["data"]["call_number"] == 1


async def test_execute_skill_with_dedup_reruns_for_a_different_thread_id(require_postgres):
    # Sanity check on the other side of the UNIQUE constraint: a different
    # thread_id is a different workflow run, so it must execute for real.
    context = SkillContext(
        user_id="user-1",
        conversation_id="conv-1",
        project_id=None,
        workspace_id=None,
        local_only=False,
        granted_scopes=set(),
    )
    arguments = {"foo": "bar"}
    call_count = 0

    class FakeSkill:
        async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
            nonlocal call_count
            call_count += 1
            return SkillResult(success=True, summary="ran", data={"call_number": call_count})

    skill = FakeSkill()

    await execute_skill_with_dedup(str(uuid.uuid4()), "fake.tool", arguments, context, skill)
    await execute_skill_with_dedup(str(uuid.uuid4()), "fake.tool", arguments, context, skill)

    assert call_count == 2
