"""Integration tests for the Workspaces API (SPEC.md §9 Development Mode,
§25 DoD "승인 전 commit 금지"). No real DB and no real git worktree: both
the workspaces repository and the GitWorktreeRuntime dependency are swapped
for in-memory fakes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.approvals_repository import get_approvals_repository
from personal_ai_api.main import app
from personal_ai_api.workspaces import get_workspace_runtime
from personal_ai_api.workspaces_repository import (
    WorkspaceRecord,
    WorkspaceRecordNotFound,
    get_workspaces_repository,
)

from personal_ai.development.workspace import WorkspaceNotFound


class FakeWorkspacesRepository:
    def __init__(self) -> None:
        self.workspaces: dict[str, WorkspaceRecord] = {}
        self.runs: list[dict] = []

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_workspace(
        self, user_id, workspace_id, source_path, workspace_dir
    ) -> WorkspaceRecord:
        # id must equal the runtime's workspace_id -- see the matching
        # comment in the real SqlAlchemyWorkspacesRepository.
        record = WorkspaceRecord(
            id=workspace_id,
            source_path=source_path,
            workspace_dir=workspace_dir,
            status="active",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        self.workspaces[record.id] = record
        return record

    async def get_workspace(self, workspace_id, user_id) -> WorkspaceRecord:
        if workspace_id not in self.workspaces:
            raise WorkspaceRecordNotFound(workspace_id)
        return self.workspaces[workspace_id]

    async def update_workspace(self, workspace_id, user_id, updates) -> WorkspaceRecord:
        if workspace_id not in self.workspaces:
            raise WorkspaceRecordNotFound(workspace_id)
        current = self.workspaces[workspace_id]
        record = WorkspaceRecord(**{**vars(current), **updates})
        self.workspaces[workspace_id] = record
        return record

    async def record_run(
        self, workspace_id, command, exit_code, stdout, stderr, duration_ms
    ) -> None:
        self.runs.append(
            {
                "workspace_id": workspace_id,
                "command": command,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
            }
        )


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
        record = {
            "id": f"approval-{self._counter}",
            "action": action,
            "target": target,
            "risk_level": risk_level,
            "arguments": arguments,
            "arguments_hash": arguments_hash,
            "preview": preview,
            "expected_effects": expected_effects,
            "rollback_available": rollback_available,
            "expires_at": expires_at,
        }
        self.created.append(record)

        from types import SimpleNamespace

        return SimpleNamespace(id=record["id"])


class FakeRuntime:
    """No real git/filesystem I/O -- every method is scripted per-test."""

    def __init__(self) -> None:
        self.created_from: list[str] = []
        self.ran: list[tuple[str, list[str]]] = []
        self.destroyed: list[str] = []
        self.known_workspace = "ws-remote-1"
        self.search_results = [{"path": "README.md", "matched_by": "content"}]
        self.file_content = "hello world"
        self.diff_text = "diff --git a/x b/x\n"
        self.patch_result = {"success": True, "stderr": ""}
        self.run_result = {"exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 12}
        self.deny_repo = False
        self.deny_command = False
        self.deny_path = False
        self.missing_file = False

    async def create_workspace(self, source: str) -> str:
        if self.deny_repo:
            raise PermissionError("repository not in ALLOWED_REPOS")
        self.created_from.append(source)
        return self.known_workspace

    async def search(self, workspace_id: str, query: str) -> list[dict]:
        if workspace_id != self.known_workspace:
            raise WorkspaceNotFound(workspace_id)
        return self.search_results

    async def read_file(self, workspace_id: str, path: str) -> str:
        if workspace_id != self.known_workspace:
            raise WorkspaceNotFound(workspace_id)
        if self.deny_path:
            raise PermissionError("path escapes workspace repository")
        if self.missing_file:
            raise FileNotFoundError(path)
        return self.file_content

    async def apply_patch(self, workspace_id: str, patch: str) -> dict:
        if workspace_id != self.known_workspace:
            raise WorkspaceNotFound(workspace_id)
        return self.patch_result

    async def run_command(self, workspace_id: str, command: list[str]) -> dict:
        if workspace_id != self.known_workspace:
            raise WorkspaceNotFound(workspace_id)
        if self.deny_command:
            raise PermissionError("command not allowed")
        self.ran.append((workspace_id, command))
        return self.run_result

    async def get_diff(self, workspace_id: str) -> str:
        if workspace_id != self.known_workspace:
            raise WorkspaceNotFound(workspace_id)
        return self.diff_text

    async def destroy_workspace(self, workspace_id: str) -> None:
        self.destroyed.append(workspace_id)


@pytest.fixture
def repository() -> FakeWorkspacesRepository:
    return FakeWorkspacesRepository()


@pytest.fixture
def approvals_repository() -> FakeApprovalsRepository:
    return FakeApprovalsRepository()


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def client(
    repository: FakeWorkspacesRepository,
    approvals_repository: FakeApprovalsRepository,
    runtime: FakeRuntime,
):
    app.dependency_overrides[get_workspaces_repository] = lambda: repository
    app.dependency_overrides[get_approvals_repository] = lambda: approvals_repository
    app.dependency_overrides[get_workspace_runtime] = lambda: runtime
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create(client: TestClient) -> dict:
    return client.post("/api/v1/workspaces", json={"source": "/repos/acme"}).json()


def test_create_workspace_returns_201(client: TestClient, runtime: FakeRuntime) -> None:
    response = client.post("/api/v1/workspaces", json={"source": "/repos/acme"})

    assert response.status_code == 201
    body = response.json()
    assert body["source_path"] == "/repos/acme"
    assert body["status"] == "active"
    assert "id" in body and "workspace_dir" in body
    assert runtime.created_from == ["/repos/acme"]


def test_create_workspace_disallowed_repo_returns_403(
    client: TestClient, runtime: FakeRuntime
) -> None:
    runtime.deny_repo = True

    response = client.post("/api/v1/workspaces", json={"source": "/not/allowed"})

    assert response.status_code == 403
    assert response.json()["detail"] == "repository not in allowed list"


def test_get_unknown_workspace_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/workspaces/does-not-exist")

    assert response.status_code == 404


def test_get_created_workspace_returns_it(client: TestClient) -> None:
    created = _create(client)

    response = client.get(f"/api/v1/workspaces/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_run_command_returns_result_and_records_it(
    client: TestClient, repository: FakeWorkspacesRepository, runtime: FakeRuntime
) -> None:
    created = _create(client)

    response = client.post(f"/api/v1/workspaces/{created['id']}/run", json={"command": ["pytest"]})

    assert response.status_code == 200
    body = response.json()
    assert body["exit_code"] == 0
    assert body["stdout"] == "ok"
    assert len(repository.runs) == 1
    assert repository.runs[0]["command"] == ["pytest"]
    assert runtime.ran == [(created["id"], ["pytest"])]


def test_run_disallowed_command_returns_403(client: TestClient, runtime: FakeRuntime) -> None:
    created = _create(client)
    runtime.deny_command = True

    response = client.post(f"/api/v1/workspaces/{created['id']}/run", json={"command": ["rm"]})

    assert response.status_code == 403


def test_run_command_unknown_workspace_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/workspaces/does-not-exist/run", json={"command": ["pytest"]})

    assert response.status_code == 404


def test_get_diff_returns_diff_text(client: TestClient) -> None:
    created = _create(client)

    response = client.get(f"/api/v1/workspaces/{created['id']}/diff")

    assert response.status_code == 200
    assert response.json() == {"diff": "diff --git a/x b/x\n"}


def test_search_workspace_returns_matches(client: TestClient) -> None:
    created = _create(client)

    response = client.post(f"/api/v1/workspaces/{created['id']}/search", json={"query": "hello"})

    assert response.status_code == 200
    assert response.json() == [{"path": "README.md", "matched_by": "content"}]


def test_read_file_returns_content(client: TestClient) -> None:
    created = _create(client)

    response = client.get(f"/api/v1/workspaces/{created['id']}/file", params={"path": "a.py"})

    assert response.status_code == 200
    assert response.json() == {"content": "hello world"}


def test_read_file_path_escape_returns_403(client: TestClient, runtime: FakeRuntime) -> None:
    created = _create(client)
    runtime.deny_path = True

    response = client.get(
        f"/api/v1/workspaces/{created['id']}/file", params={"path": "../../etc/passwd"}
    )

    assert response.status_code == 403


def test_read_missing_file_returns_404(client: TestClient, runtime: FakeRuntime) -> None:
    created = _create(client)
    runtime.missing_file = True

    response = client.get(f"/api/v1/workspaces/{created['id']}/file", params={"path": "nope.py"})

    assert response.status_code == 404


def test_apply_patch_returns_result(client: TestClient) -> None:
    created = _create(client)

    response = client.post(
        f"/api/v1/workspaces/{created['id']}/apply-patch", json={"patch": "--- a\n+++ b\n"}
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "stderr": ""}


def test_commit_creates_pending_approval_and_never_commits(
    client: TestClient, approvals_repository: FakeApprovalsRepository
) -> None:
    """SPEC §25 DoD 'commit 승인 전 금지': the endpoint must return
    pending_approval, not actually run git commit."""
    created = _create(client)

    response = client.post(
        f"/api/v1/workspaces/{created['id']}/commit", json={"message": "fix bug"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["approval_id"]

    assert len(approvals_repository.created) == 1
    approval = approvals_repository.created[0]
    assert approval["action"] == f"workspace_commit:{created['id']}"
    assert approval["target"] == created["id"]
    assert approval["risk_level"] == "medium"
    assert approval["arguments"] == {"workspace_id": created["id"], "message": "fix bug"}
    assert approval["rollback_available"] is False


def test_commit_unknown_workspace_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/workspaces/does-not-exist/commit", json={"message": "x"})

    assert response.status_code == 404


def test_destroy_workspace_marks_status_destroyed(client: TestClient, runtime: FakeRuntime) -> None:
    created = _create(client)

    response = client.delete(f"/api/v1/workspaces/{created['id']}")

    assert response.status_code == 204
    assert runtime.destroyed == [created["id"]]

    after = client.get(f"/api/v1/workspaces/{created['id']}").json()
    assert after["status"] == "destroyed"


def test_destroy_unknown_workspace_returns_404(client: TestClient) -> None:
    response = client.delete("/api/v1/workspaces/does-not-exist")

    assert response.status_code == 404
