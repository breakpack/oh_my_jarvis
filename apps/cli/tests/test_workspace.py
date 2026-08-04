import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    commit_workspace,
    create_workspace,
    destroy_workspace,
    fetch_workspace_diff,
    render_workspace_run_result,
    run_workspace_command,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


WORKSPACE = {
    "id": "ws-1",
    "source_path": "acme/widgets",
    "workspace_dir": "/workspaces/ws-1",
    "status": "ready",
    "created_at": "2026-08-04T00:00:00Z",
}


def test_create_workspace_sends_source_and_returns_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/workspaces"
        return httpx.Response(200, content=json.dumps(WORKSPACE).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = create_workspace(client, "http://testserver", "acme/widgets")
    finally:
        client.close()

    assert result == WORKSPACE
    assert captured["body"] == {"source": "acme/widgets"}


def test_create_workspace_raises_api_error_on_403_disallowed_repo() -> None:
    client = _client(403, {"detail": "repository not in allowed list"})
    try:
        with pytest.raises(ApiError, match="repository not in allowed list"):
            create_workspace(client, "http://testserver", "evil/repo")
    finally:
        client.close()


def test_run_workspace_command_sends_command_list() -> None:
    captured: dict[str, object] = {}
    run_result = {"exit_code": 0, "stdout": "ok\n", "stderr": "", "duration_ms": 42}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps(run_result).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = run_workspace_command(client, "http://testserver", "ws-1", ["ls", "-la"])
    finally:
        client.close()

    assert result == run_result
    assert captured["path"] == "/api/v1/workspaces/ws-1/run"
    assert captured["body"] == {"command": ["ls", "-la"]}
    render_workspace_run_result(result)


def test_run_workspace_command_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "workspace not found"})
    try:
        with pytest.raises(ApiError, match="workspace not found"):
            run_workspace_command(client, "http://testserver", "missing-ws", ["ls"])
    finally:
        client.close()


def test_run_workspace_command_renders_nonzero_exit_code() -> None:
    failed_result = {"exit_code": 1, "stdout": "", "stderr": "boom", "duration_ms": 5}
    render_workspace_run_result(failed_result)


def test_fetch_workspace_diff_returns_diff_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workspaces/ws-1/diff"
        return httpx.Response(200, content=json.dumps({"diff": "+added line"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_workspace_diff(client, "http://testserver", "ws-1")
    finally:
        client.close()

    assert result == {"diff": "+added line"}


def test_fetch_workspace_diff_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "workspace not found"})
    try:
        with pytest.raises(ApiError, match="workspace not found"):
            fetch_workspace_diff(client, "http://testserver", "missing-ws")
    finally:
        client.close()


def test_commit_workspace_sends_message() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps({"status": "committed"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = commit_workspace(client, "http://testserver", "ws-1", "fix bug")
    finally:
        client.close()

    assert result == {"status": "committed"}
    assert captured["body"] == {"message": "fix bug"}


def test_commit_workspace_returns_pending_approval_body_on_202() -> None:
    pending_body = {"status": "pending_approval", "approval_id": "appr-1"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=json.dumps(pending_body).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = commit_workspace(client, "http://testserver", "ws-1", "fix bug")
    finally:
        client.close()

    assert result == pending_body


def test_commit_workspace_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "workspace not found"})
    try:
        with pytest.raises(ApiError, match="workspace not found"):
            commit_workspace(client, "http://testserver", "missing-ws", "fix bug")
    finally:
        client.close()


def test_destroy_workspace_sends_delete() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(204, content=b"")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        destroy_workspace(client, "http://testserver", "ws-1")
    finally:
        client.close()

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/workspaces/ws-1"


def test_destroy_workspace_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "workspace not found"})
    try:
        with pytest.raises(ApiError, match="workspace not found"):
            destroy_workspace(client, "http://testserver", "missing-ws")
    finally:
        client.close()
