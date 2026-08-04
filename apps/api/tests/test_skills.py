"""Integration tests for the Skills API (SPEC.md §6.5, §6.6, §15, §20.4).

Discovery is exercised against the repo's real `skills/` directory (not a
fake) for the list/get/enable/disable/501-stub/query-filter cases per this
phase's brief — those don't touch the database. The one DB-backed piece
(the audit repository used by /run and /audit) is swapped for an in-memory
fake, and /run itself is never called end-to-end here (it would shell out
to `gh`/hit the filesystem for real) — only the disabled/stub short-circuit
paths that return before touching the repository.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from personal_ai_api import skills_service
from personal_ai_api.approvals_repository import get_approvals_repository
from personal_ai_api.main import app
from personal_ai_api.skills_service import get_skills_repository


class FakeApprovalsRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self._counter = 0

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_approval(
        self,
        user_id,
        action,
        target,
        risk_level,
        arguments,
        arguments_hash,
        preview,
        expected_effects,
        rollback_available,
        expires_at,
    ):
        self._counter += 1
        record = SimpleNamespace(
            id=f"approval-{self._counter}",
            user_id=user_id,
            action=action,
            target=target,
            risk_level=risk_level,
            arguments=arguments,
            arguments_hash=arguments_hash,
            preview=preview,
            expected_effects=expected_effects,
            rollback_available=rollback_available,
            expires_at=expires_at,
            status="pending",
        )
        self.created.append(vars(record))
        return record


class FakeSkillsRepository:
    def __init__(self) -> None:
        self.audit_events: list[dict] = []

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None:
        self.audit_events.append({"user_id": user_id, "event_type": event_type, "payload": payload})

    async def list_skill_audit(self, skill_name: str, limit: int = 20) -> list[dict]:
        return [
            {
                "id": f"evt-{i}",
                "event_type": e["event_type"],
                "payload": e["payload"],
                "created_at": "2026-01-01T00:00:00",
            }
            for i, e in enumerate(self.audit_events)
            if e["payload"].get("skill") == skill_name
        ][:limit]


@pytest.fixture(autouse=True)
def _fresh_skill_cache():
    """Each test starts from a clean discover() so enable/disable state
    from one test can't leak into the next."""
    skills_service.reset_cache()
    yield
    skills_service.reset_cache()


@pytest.fixture
def repository() -> FakeSkillsRepository:
    return FakeSkillsRepository()


@pytest.fixture
def approvals_repository() -> FakeApprovalsRepository:
    return FakeApprovalsRepository()


@pytest.fixture
def client(repository: FakeSkillsRepository, approvals_repository: FakeApprovalsRepository):
    app.dependency_overrides[get_skills_repository] = lambda: repository
    app.dependency_overrides[get_approvals_repository] = lambda: approvals_repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_skills_includes_the_real_working_skills(client: TestClient) -> None:
    response = client.get("/api/v1/skills")

    assert response.status_code == 200
    body = response.json()
    names = {s["name"] for s in body["skills"]}
    assert {"github-issues-lookup", "local-file-search"} <= names


def test_list_skills_includes_the_real_stub_skills_as_enabled(client: TestClient) -> None:
    response = client.get("/api/v1/skills")

    assert response.status_code == 200
    by_name = {s["name"]: s for s in response.json()["skills"]}
    assert "calendar-lookup" in by_name
    assert "notion-lookup" in by_name
    assert by_name["calendar-lookup"]["enabled"] is True
    assert by_name["notion-lookup"]["enabled"] is True


def test_list_skills_exposes_invalid_manifests_instead_of_hiding_them(
    monkeypatch, tmp_path
) -> None:
    """SPEC §25 DoD 'invalid manifest blocked': a broken skill must not
    silently vanish -- it should still show up in `invalid`."""
    good = tmp_path / "good-skill"
    good.mkdir()
    (good / "manifest.yaml").write_text(
        "api_version: personal-ai-os/v1\n"
        "kind: Skill\n"
        "metadata:\n"
        "  name: good-skill\n"
        "  display_name: Good Skill\n"
        "  version: 0.1.0\n"
        "  description: A valid skill.\n"
        "  license: MIT\n"
        "  author: local\n"
        "  tags: []\n"
        "runtime:\n"
        "  type: python\n"
        "  entrypoint: workflow.py\n"
        "  timeout_seconds: 30\n"
        "  network_access: none\n"
        "models:\n"
        "  preferred: []\n"
        "  local_only_supported: true\n"
        "capabilities:\n"
        "  tools: []\n"
        "  resources: []\n"
        "permissions:\n"
        "  risk_level: read\n"
        "  scopes: []\n"
        "input_schema: input.schema.json\n"
        "output_schema: output.schema.json\n",
        encoding="utf-8",
    )
    (good / "SKILL.md").write_text("# Good Skill\n", encoding="utf-8")

    broken = tmp_path / "broken-skill"
    broken.mkdir()
    (broken / "manifest.yaml").write_text("kind: Skill\n", encoding="utf-8")
    (broken / "SKILL.md").write_text("# Broken Skill\n", encoding="utf-8")

    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path)
    skills_service.reset_cache()
    app.dependency_overrides[get_skills_repository] = lambda: FakeSkillsRepository()
    try:
        response = TestClient(app).get("/api/v1/skills")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert {s["name"] for s in body["skills"]} == {"good-skill"}
    assert [i["path"] for i in body["invalid"]] == ["broken-skill"]
    assert body["invalid"][0]["error"]


def test_get_known_skill_returns_manifest_and_skill_md(client: TestClient) -> None:
    response = client.get("/api/v1/skills/github-issues-lookup")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "github-issues-lookup"
    assert body["manifest"]["metadata"]["name"] == "github-issues-lookup"
    assert body["enabled"] is True
    assert isinstance(body["skill_md"], dict)


def test_get_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/skills/does-not-exist")

    assert response.status_code == 404


def test_enable_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/skills/does-not-exist/enable")

    assert response.status_code == 404


def test_disable_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/skills/does-not-exist/disable")

    assert response.status_code == 404


def test_disable_then_enable_round_trips(client: TestClient) -> None:
    disable_response = client.post("/api/v1/skills/local-file-search/disable")
    assert disable_response.status_code == 200
    assert disable_response.json() == {"name": "local-file-search", "enabled": False}

    listed = client.get("/api/v1/skills").json()
    by_name = {s["name"]: s for s in listed["skills"]}
    assert by_name["local-file-search"]["enabled"] is False

    enable_response = client.post("/api/v1/skills/local-file-search/enable")
    assert enable_response.status_code == 200
    assert enable_response.json() == {"name": "local-file-search", "enabled": True}


def test_run_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/skills/does-not-exist/run", json={"arguments": {}})

    assert response.status_code == 404


def test_run_disabled_skill_returns_409(client: TestClient) -> None:
    client.post("/api/v1/skills/github-issues-lookup/disable")

    response = client.post("/api/v1/skills/github-issues-lookup/run", json={"arguments": {}})

    assert response.status_code == 409
    assert response.json()["detail"] == "skill disabled"


def test_run_calendar_lookup_stub_returns_501(client: TestClient) -> None:
    response = client.post("/api/v1/skills/calendar-lookup/run", json={"arguments": {}})

    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"]


def test_run_notion_lookup_stub_returns_501(client: TestClient) -> None:
    response = client.post("/api/v1/skills/notion-lookup/run", json={"arguments": {}})

    assert response.status_code == 501
    assert "not yet implemented" in response.json()["detail"]


def test_run_medium_risk_skill_creates_approval_instead_of_executing(
    client: TestClient, approvals_repository: FakeApprovalsRepository
) -> None:
    """SPEC §25 DoD '승인 전 실행 불가': github-issue-create is manifest
    risk_level=medium, so /run must never call execute() -- it should
    create a pending Approval and return 202 instead."""
    response = client.post(
        "/api/v1/skills/github-issue-create/run",
        json={"arguments": {"repo": "acme/widgets", "title": "Bug: widget explodes"}},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["approval_id"]

    assert len(approvals_repository.created) == 1
    approval = approvals_repository.created[0]
    assert approval["action"] == "skill:github-issue-create"
    assert approval["risk_level"] == "medium"
    assert approval["target"] == "acme/widgets"
    assert approval["arguments"] == {"repo": "acme/widgets", "title": "Bug: widget explodes"}
    assert approval["rollback_available"] is True
    assert approval["status"] == "pending"


def test_query_param_ranks_the_best_matching_skill_first(client: TestClient) -> None:
    # "이슈 목록 조회" (list/query issues) scores github-issues-lookup 2
    # (description + Trigger Conditions both use "이슈"/"조회") vs. 1 for
    # github-issue-create and calendar-lookup -- a query like plain "github
    # issues" is ambiguous now that github-issue-create shares the same
    # tags, so this query is chosen for an unambiguous score margin.
    response = client.get("/api/v1/skills", params={"query": "이슈 목록 조회", "top_k": 1})

    assert response.status_code == 200
    skills = response.json()["skills"]
    assert len(skills) == 1
    assert skills[0]["name"] == "github-issues-lookup"


def test_get_audit_for_unknown_skill_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/skills/does-not-exist/audit")

    assert response.status_code == 404


def test_get_audit_returns_events_recorded_for_that_skill(
    client: TestClient, repository: FakeSkillsRepository
) -> None:
    repository.audit_events.append(
        {
            "user_id": "user-1",
            "event_type": "skill_run",
            "payload": {"skill": "github-issues-lookup", "success": True, "duration_ms": 12},
        }
    )
    repository.audit_events.append(
        {
            "user_id": "user-1",
            "event_type": "skill_run",
            "payload": {"skill": "local-file-search", "success": True, "duration_ms": 5},
        }
    )

    response = client.get("/api/v1/skills/github-issues-lookup/audit")

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["payload"]["skill"] == "github-issues-lookup"
