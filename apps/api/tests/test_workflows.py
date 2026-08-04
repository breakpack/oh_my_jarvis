"""Integration tests for the durable Workflow API (SPEC.md §5.2, §15, §25
DoD). No real LangGraph/Postgres: run_skill_workflow and
resume_skill_workflow are monkeypatched at the point workflows.py imported
them, so only the 202/200/422/404/501 routing logic is under test here.
"""

from __future__ import annotations

import personal_ai_api.workflows as workflows_module
import pytest
from fastapi.testclient import TestClient
from personal_ai_api.db import get_default_user_id
from personal_ai_api.main import app

from personal_ai.workflows.skill_run_graph import SkillNotFoundError, SkillNotImplementedError


@pytest.fixture
def client():
    app.dependency_overrides[get_default_user_id] = lambda: "user-1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_run_pending_approval_returns_202(client: TestClient, monkeypatch) -> None:
    captured = {}

    async def fake_run(skill_name, arguments, user_id):
        captured["args"] = (skill_name, arguments, user_id)
        return {
            "status": "pending_approval",
            "thread_id": "thread-1",
            "interrupt": {
                "reason": "approval_required",
                "skill": skill_name,
                "arguments": arguments,
                "preview": [{"step": "call_tool"}],
            },
        }

    monkeypatch.setattr(workflows_module, "run_skill_workflow", fake_run)

    response = client.post(
        "/api/v1/workflows/skills/github-issue-create/run",
        json={"arguments": {"repo": "acme/widgets", "title": "Bug"}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["thread_id"] == "thread-1"
    assert body["interrupt"]["skill"] == "github-issue-create"
    assert captured["args"] == (
        "github-issue-create",
        {"repo": "acme/widgets", "title": "Bug"},
        "user-1",
    )


def test_run_completed_returns_200(client: TestClient, monkeypatch) -> None:
    async def fake_run(skill_name, arguments, user_id):
        return {
            "status": "completed",
            "thread_id": "thread-2",
            "result": {"success": True, "summary": "done", "data": None, "error": None},
        }

    monkeypatch.setattr(workflows_module, "run_skill_workflow", fake_run)

    response = client.post(
        "/api/v1/workflows/skills/github-issues-lookup/run",
        json={"arguments": {"repo": "acme/widgets"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["result"]["success"] is True


def test_run_defaults_arguments_to_empty_dict(client: TestClient, monkeypatch) -> None:
    captured = {}

    async def fake_run(skill_name, arguments, user_id):
        captured["arguments"] = arguments
        return {"status": "completed", "thread_id": "t", "result": {"success": True}}

    monkeypatch.setattr(workflows_module, "run_skill_workflow", fake_run)

    response = client.post("/api/v1/workflows/skills/local-file-search/run", json={})

    assert response.status_code == 200
    assert captured["arguments"] == {}


def test_run_unknown_skill_returns_404(client: TestClient, monkeypatch) -> None:
    async def fake_run(skill_name, arguments, user_id):
        raise SkillNotFoundError(skill_name)

    monkeypatch.setattr(workflows_module, "run_skill_workflow", fake_run)

    response = client.post("/api/v1/workflows/skills/does-not-exist/run", json={"arguments": {}})

    assert response.status_code == 404


def test_run_stub_skill_returns_501(client: TestClient, monkeypatch) -> None:
    async def fake_run(skill_name, arguments, user_id):
        raise SkillNotImplementedError(skill_name)

    monkeypatch.setattr(workflows_module, "run_skill_workflow", fake_run)

    response = client.post("/api/v1/workflows/skills/calendar-lookup/run", json={"arguments": {}})

    assert response.status_code == 501


def test_resume_approve_pending_returns_202(client: TestClient, monkeypatch) -> None:
    captured = {}

    async def fake_resume(thread_id, decision):
        captured["args"] = (thread_id, decision)
        return {
            "status": "pending_approval",
            "thread_id": thread_id,
            "interrupt": {"reason": "approval_required"},
        }

    monkeypatch.setattr(workflows_module, "resume_skill_workflow", fake_resume)

    response = client.post("/api/v1/workflows/thread-3/resume", json={"decision": "approve"})

    assert response.status_code == 202
    assert response.json()["thread_id"] == "thread-3"
    assert captured["args"] == ("thread-3", "approve")


def test_resume_approve_completed_returns_200(client: TestClient, monkeypatch) -> None:
    async def fake_resume(thread_id, decision):
        return {
            "status": "completed",
            "thread_id": thread_id,
            "result": {"success": True, "summary": "done"},
        }

    monkeypatch.setattr(workflows_module, "resume_skill_workflow", fake_resume)

    response = client.post("/api/v1/workflows/thread-4/resume", json={"decision": "approve"})

    assert response.status_code == 200
    assert response.json()["result"]["success"] is True


def test_resume_reject_returns_completed_failure(client: TestClient, monkeypatch) -> None:
    async def fake_resume(thread_id, decision):
        assert decision == "reject"
        return {
            "status": "completed",
            "thread_id": thread_id,
            "result": {"success": False, "error": "approval rejected"},
        }

    monkeypatch.setattr(workflows_module, "resume_skill_workflow", fake_resume)

    response = client.post("/api/v1/workflows/thread-5/resume", json={"decision": "reject"})

    assert response.status_code == 200
    assert response.json()["result"]["success"] is False


def test_resume_invalid_decision_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/workflows/thread-6/resume", json={"decision": "maybe"})

    assert response.status_code == 422


def test_resume_missing_decision_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/workflows/thread-7/resume", json={})

    assert response.status_code == 422


def test_resume_unknown_thread_returns_404(client: TestClient, monkeypatch) -> None:
    async def fake_resume(thread_id, decision):
        raise SkillNotFoundError("some-skill")

    monkeypatch.setattr(workflows_module, "resume_skill_workflow", fake_resume)

    response = client.post("/api/v1/workflows/does-not-exist/resume", json={"decision": "approve"})

    assert response.status_code == 404
