import json

import httpx
import pytest
import typer
from personal_ai_cli.main import (
    ApiError,
    render_workflow_response,
    resume_workflow,
    run_workflow,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_workflow_sends_arguments_to_the_right_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=json.dumps({"status": "completed", "thread_id": "t1"}).encode()
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        run_workflow(client, "http://testserver", "github-issue-create", {"repo": "acme/x"})
    finally:
        client.close()

    assert captured["path"] == "/api/v1/workflows/skills/github-issue-create/run"
    assert captured["body"] == {"arguments": {"repo": "acme/x"}}


def test_run_workflow_returns_pending_approval_body_on_202() -> None:
    pending_body = {
        "status": "pending_approval",
        "thread_id": "thread-1",
        "interrupt": {"reason": "approval_required", "skill": "github-issue-create"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=json.dumps(pending_body).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = run_workflow(client, "http://testserver", "github-issue-create", {})
    finally:
        client.close()

    assert result == pending_body


def test_run_workflow_returns_completed_body_on_200() -> None:
    completed_body = {
        "status": "completed",
        "thread_id": "thread-2",
        "result": {"success": True, "summary": "Found 3 issues"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(completed_body).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = run_workflow(client, "http://testserver", "github-issues-lookup", {})
    finally:
        client.close()

    assert result == completed_body


def test_run_workflow_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "skill 'does-not-exist' not found"})
    try:
        with pytest.raises(ApiError, match="not found"):
            run_workflow(client, "http://testserver", "does-not-exist", {})
    finally:
        client.close()


def test_run_workflow_raises_api_error_on_501() -> None:
    client = _client(501, {"detail": "skill 'calendar-lookup' is not yet implemented"})
    try:
        with pytest.raises(ApiError, match="not yet implemented"):
            run_workflow(client, "http://testserver", "calendar-lookup", {})
    finally:
        client.close()


def test_resume_workflow_sends_decision_to_the_right_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=json.dumps(
                {"status": "completed", "thread_id": "thread-3", "result": {"success": True}}
            ).encode(),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        resume_workflow(client, "http://testserver", "thread-3", "approve")
    finally:
        client.close()

    assert captured["path"] == "/api/v1/workflows/thread-3/resume"
    assert captured["body"] == {"decision": "approve"}


def test_resume_workflow_returns_pending_approval_body_on_202() -> None:
    pending_body = {
        "status": "pending_approval",
        "thread_id": "thread-4",
        "interrupt": {"reason": "approval_required"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, content=json.dumps(pending_body).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = resume_workflow(client, "http://testserver", "thread-4", "approve")
    finally:
        client.close()

    assert result == pending_body


def test_resume_workflow_raises_api_error_on_422_invalid_decision() -> None:
    client = _client(422, {"detail": "decision must be 'approve' or 'reject'"})
    try:
        with pytest.raises(ApiError, match="approve"):
            resume_workflow(client, "http://testserver", "thread-5", "maybe")
    finally:
        client.close()


def test_render_workflow_response_pending_approval_does_not_exit() -> None:
    render_workflow_response(
        {"status": "pending_approval", "thread_id": "thread-6", "interrupt": {}}
    )


def test_render_workflow_response_completed_success_does_not_exit() -> None:
    render_workflow_response(
        {
            "status": "completed",
            "thread_id": "thread-7",
            "result": {"success": True, "summary": "done"},
        }
    )


def test_render_workflow_response_completed_failure_raises_exit() -> None:
    with pytest.raises(typer.Exit):
        render_workflow_response(
            {
                "status": "completed",
                "thread_id": "thread-8",
                "result": {"success": False, "summary": "rejected", "error": "approval rejected"},
            }
        )
