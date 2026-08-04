"""Integration tests for the Approvals API (SPEC.md §12 Policy/Approval,
§20.4 Audit). No real DB: the approvals repository dependency is swapped
for an in-memory fake. Approving a skill: action replays the real
github-issue-create skill's plan/execute/verify -- execute() itself is
monkeypatched so no real `gh` call happens, matching how test_skills.py
avoids real Tool calls. Approving a workspace_commit: action runs real
`git add`/`git commit` against a scratch tmp_path repo (no mocking needed
for plain `git`), which is the actual, strongest verification of the
"add-then-commit, in order" requirement.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.approvals_repository import (
    ApprovalNotFound,
    ApprovalRecord,
    get_approvals_repository,
)
from personal_ai_api.main import app
from personal_ai_api.workspaces_repository import (
    WorkspaceRecord,
    WorkspaceRecordNotFound,
    get_workspaces_repository,
)

from personal_ai.security.approval import compute_arguments_hash


class FakeApprovalsRepository:
    def __init__(self) -> None:
        self.approvals: dict[str, ApprovalRecord] = {}
        self.audit_events: list[dict] = []
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"approval-{self._counter}"

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
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            id=self._new_id(),
            action=action,
            target=target,
            risk_level=risk_level,
            arguments=arguments,
            arguments_hash=arguments_hash,
            preview=preview,
            expected_effects=expected_effects,
            rollback_available=rollback_available,
            rollback_token=None,
            status="pending",
            expires_at=expires_at.isoformat() if expires_at else None,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        self.approvals[record.id] = record
        return record

    async def list_approvals(self, user_id, status="pending") -> list[ApprovalRecord]:
        results = list(self.approvals.values())
        if status:
            results = [a for a in results if a.status == status]
        return results

    async def get_approval(self, approval_id, user_id) -> ApprovalRecord:
        if approval_id not in self.approvals:
            raise ApprovalNotFound(approval_id)
        return self.approvals[approval_id]

    async def update_approval(self, approval_id, user_id, updates) -> ApprovalRecord:
        if approval_id not in self.approvals:
            raise ApprovalNotFound(approval_id)
        current = self.approvals[approval_id]
        record = ApprovalRecord(**{**vars(current), **updates})
        self.approvals[approval_id] = record
        return record

    async def record_audit(self, user_id, event_type, payload) -> None:
        self.audit_events.append({"user_id": user_id, "event_type": event_type, "payload": payload})


class FakeWorkspacesRepository:
    def __init__(self) -> None:
        self.workspaces: dict[str, WorkspaceRecord] = {}

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def get_workspace(self, workspace_id, user_id) -> WorkspaceRecord:
        if workspace_id not in self.workspaces:
            raise WorkspaceRecordNotFound(workspace_id)
        return self.workspaces[workspace_id]

    async def create_workspace(self, user_id, workspace_id, source_path, workspace_dir):
        raise NotImplementedError("not needed by approvals.py")

    async def update_workspace(self, workspace_id, user_id, updates):
        raise NotImplementedError("not needed by approvals.py")

    async def record_run(self, *args, **kwargs):
        raise NotImplementedError("not needed by approvals.py")


def _init_git_repo(base_dir: Path) -> Path:
    """A real (scratch) git repo -- plain `git` needs no mocking, and
    actually running it is the strongest proof of "add ran before commit"."""
    repository_dir = base_dir / "repository"
    repository_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repository_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repository_dir, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository_dir, check=True)
    (repository_dir / "README.md").write_text("hello\n", encoding="utf-8")
    return repository_dir


def _seed(repository: FakeApprovalsRepository, **overrides) -> ApprovalRecord:
    arguments = overrides.pop("arguments", {"repo": "acme/widgets", "title": "Bug report"})
    defaults = dict(
        action="skill:github-issue-create",
        target="acme/widgets",
        risk_level="medium",
        arguments=arguments,
        arguments_hash=compute_arguments_hash(arguments),
        preview="[{'step': 'call_tool', 'tool': 'github.create_issue'}]",
        expected_effects=["Executes github-issue-create with medium risk"],
        rollback_available=True,
        expires_at=None,
        status="pending",
    )
    defaults.update(overrides)
    record = ApprovalRecord(
        id=repository._new_id(),
        rollback_token=None,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        **defaults,
    )
    repository.approvals[record.id] = record
    return record


@pytest.fixture
def repository() -> FakeApprovalsRepository:
    return FakeApprovalsRepository()


@pytest.fixture
def workspaces_repository() -> FakeWorkspacesRepository:
    return FakeWorkspacesRepository()


@pytest.fixture
def client(repository: FakeApprovalsRepository, workspaces_repository: FakeWorkspacesRepository):
    app.dependency_overrides[get_approvals_repository] = lambda: repository
    app.dependency_overrides[get_workspaces_repository] = lambda: workspaces_repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_approvals_defaults_to_pending(client: TestClient, repository) -> None:
    pending = _seed(repository)
    approved = _seed(repository, status="approved")

    response = client.get("/api/v1/approvals")

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert ids == {pending.id}
    assert approved.id not in ids


def test_list_approvals_can_filter_by_status(client: TestClient, repository) -> None:
    _seed(repository)
    rejected = _seed(repository, status="rejected")

    response = client.get("/api/v1/approvals", params={"status": "rejected"})

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()}
    assert ids == {rejected.id}


def test_approve_unknown_approval_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/approvals/does-not-exist/approve")

    assert response.status_code == 404


def test_approve_non_pending_approval_returns_409(client: TestClient, repository) -> None:
    approval = _seed(repository, status="rejected")

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"] == "approval is rejected"


def test_approve_expired_approval_returns_410_and_updates_status(
    client: TestClient, repository
) -> None:
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    approval = _seed(repository, expires_at=past)

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 410
    assert response.json()["detail"] == "approval expired"
    assert repository.approvals[approval.id].status == "expired"


def test_approve_with_tampered_arguments_returns_409_hash_mismatch(
    client: TestClient, repository
) -> None:
    approval = _seed(repository)
    # Simulate a stored-hash mismatch (SPEC §12.3): the arguments on the
    # record no longer match the hash computed when the approval was
    # created -- the core invariant "Argument hash 검증" protects.
    repository.approvals[approval.id] = ApprovalRecord(
        **{**vars(approval), "arguments": {"repo": "acme/widgets", "title": "TAMPERED"}}
    )

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 409
    assert "hash mismatch" in response.json()["detail"]
    # A hash-mismatch rejection must not silently approve the tampered request.
    assert repository.approvals[approval.id].status == "pending"


def test_approve_executes_the_skill_and_marks_approved(
    client: TestClient, repository, monkeypatch
) -> None:
    """Approving replays github-issue-create's real plan/execute/verify.
    Only the underlying Tool call (GithubCreateIssueTool.execute, which
    shells out to `gh`) is faked -- the Skill's own plan/execute/verify
    logic, the approval status transition, and the audit log all run for
    real, matching how test_skills.py avoids real Tool calls elsewhere.
    """
    from personal_ai.tools.base import ToolResult
    from personal_ai.tools.github_write import GithubCreateIssueTool

    async def fake_execute(self, arguments, context):
        return ToolResult(success=True, data={"number": 42, "url": "https://example/issues/42"})

    monkeypatch.setattr(GithubCreateIssueTool, "execute", fake_execute)

    approval = _seed(repository)

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["rollback_token"] == '{"repo": "acme/widgets", "issue_number": 42}'

    updated = repository.approvals[approval.id]
    assert updated.status == "approved"
    assert updated.rollback_token == '{"repo": "acme/widgets", "issue_number": 42}'

    audit_types = [e["event_type"] for e in repository.audit_events]
    assert "approval_execute" in audit_types
    execute_event = next(
        e for e in repository.audit_events if e["event_type"] == "approval_execute"
    )
    assert execute_event["payload"]["approval_id"] == approval.id
    assert execute_event["payload"]["success"] is True


def test_approve_workspace_commit_runs_git_add_then_commit_in_order(
    client: TestClient, repository, workspaces_repository, tmp_path
) -> None:
    repository_dir = _init_git_repo(tmp_path)
    workspaces_repository.workspaces["ws-1"] = WorkspaceRecord(
        id="ws-1",
        source_path="/repos/acme",
        workspace_dir=str(tmp_path),
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    arguments = {"workspace_id": "ws-1", "message": "Add README"}
    approval = _seed(
        repository,
        action="workspace_commit:ws-1",
        target="ws-1",
        arguments=arguments,
        preview="git commit -m 'Add README' in workspace ws-1",
        expected_effects=["Creates a local git commit in the workspace worktree"],
        rollback_available=False,
    )

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    # README.md was untracked before approval -- if `git commit` had run
    # before `git add`, this commit would have failed with nothing staged.
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=repository_dir, capture_output=True, text=True
    )
    assert log.stdout.strip() == "Add README"
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repository_dir, capture_output=True, text=True
    )
    assert status.stdout.strip() == ""

    assert repository.approvals[approval.id].status == "approved"


def test_approve_workspace_commit_with_nothing_to_commit_returns_failure_reason(
    client: TestClient, repository, workspaces_repository, tmp_path
) -> None:
    repository_dir = _init_git_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repository_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repository_dir, check=True)

    workspaces_repository.workspaces["ws-1"] = WorkspaceRecord(
        id="ws-1",
        source_path="/repos/acme",
        workspace_dir=str(tmp_path),
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    arguments = {"workspace_id": "ws-1", "message": "Nothing to commit"}
    approval = _seed(repository, action="workspace_commit:ws-1", target="ws-1", arguments=arguments)

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]
    # The approval was still processed (consistent with the skill: branch,
    # which also marks approved regardless of the underlying result).
    assert repository.approvals[approval.id].status == "approved"


def test_approve_workspace_commit_unknown_workspace_returns_failure_reason(
    client: TestClient, repository
) -> None:
    arguments = {"workspace_id": "missing-ws", "message": "x"}
    approval = _seed(
        repository, action="workspace_commit:missing-ws", target="missing-ws", arguments=arguments
    )

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "not found" in body["error"]


def test_approve_unsupported_action_returns_400(client: TestClient, repository) -> None:
    approval = _seed(repository, action="something-else")

    response = client.post(f"/api/v1/approvals/{approval.id}/approve")

    assert response.status_code == 400


def test_reject_unknown_approval_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/approvals/does-not-exist/reject")

    assert response.status_code == 404


def test_reject_pending_approval_returns_204_and_updates_status(
    client: TestClient, repository
) -> None:
    approval = _seed(repository)

    response = client.post(f"/api/v1/approvals/{approval.id}/reject")

    assert response.status_code == 204
    assert repository.approvals[approval.id].status == "rejected"
    audit_types = [e["event_type"] for e in repository.audit_events]
    assert "approval_reject" in audit_types


def test_reject_non_pending_approval_returns_409(client: TestClient, repository) -> None:
    approval = _seed(repository, status="approved")

    response = client.post(f"/api/v1/approvals/{approval.id}/reject")

    assert response.status_code == 409
    assert response.json()["detail"] == "approval is approved"
