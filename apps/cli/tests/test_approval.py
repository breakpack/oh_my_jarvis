import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    approve_approval,
    build_approvals_table,
    fetch_approvals,
    reject_approval,
    render_approval_result,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


APPROVAL = {
    "id": "appr1",
    "action": "notion.create_page",
    "target": "notion://workspace/page",
    "risk_level": "medium",
    "preview": "Create a Notion page titled 'Weekly Review'",
    "expected_effects": ["A new page is created in Notion"],
    "rollback_available": False,
    "status": "pending",
    "expires_at": "2026-08-05T00:00:00Z",
    "created_at": "2026-08-04T00:00:00Z",
}


def test_fetch_approvals_sends_status_param() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([APPROVAL]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_approvals(client, "http://testserver", "pending")
    finally:
        client.close()

    assert result == [APPROVAL]
    assert captured["params"] == {"status": "pending"}


def test_fetch_approvals_omits_status_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        fetch_approvals(client, "http://testserver", None)
    finally:
        client.close()

    assert captured["params"] == {}


def test_build_approvals_table_row_count() -> None:
    table = build_approvals_table([APPROVAL])
    assert table.row_count == 1


def test_fetch_approvals_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "approvals unavailable"})
    try:
        with pytest.raises(ApiError, match="approvals unavailable"):
            fetch_approvals(client, "http://testserver", None)
    finally:
        client.close()


def test_approve_approval_returns_skill_result_and_renders() -> None:
    skill_result = {
        "success": True,
        "summary": "Notion page created",
        "data": {"page_id": "n1"},
        "evidence": [],
        "artifacts": [],
        "rollback_token": None,
        "error": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/approvals/appr1/approve"
        return httpx.Response(200, content=json.dumps(skill_result).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = approve_approval(client, "http://testserver", "appr1")
    finally:
        client.close()

    assert result == skill_result
    render_approval_result(result)


def test_approve_approval_raises_api_error_on_404_not_found() -> None:
    client = _client(404, {"detail": "approval not found"})
    try:
        with pytest.raises(ApiError, match="approval not found"):
            approve_approval(client, "http://testserver", "missing")
    finally:
        client.close()


def test_approve_approval_raises_api_error_on_409_conflict() -> None:
    client = _client(409, {"detail": "approval already resolved"})
    try:
        with pytest.raises(ApiError, match="approval already resolved"):
            approve_approval(client, "http://testserver", "appr1")
    finally:
        client.close()


def test_approve_approval_raises_api_error_on_410_gone() -> None:
    client = _client(410, {"detail": "approval expired"})
    try:
        with pytest.raises(ApiError, match="approval expired"):
            approve_approval(client, "http://testserver", "appr1")
    finally:
        client.close()


def test_reject_approval_success_no_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/approvals/appr1/reject"
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        reject_approval(client, "http://testserver", "appr1")
    finally:
        client.close()


def test_reject_approval_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "approval not found"})
    try:
        with pytest.raises(ApiError, match="approval not found"):
            reject_approval(client, "http://testserver", "missing")
    finally:
        client.close()
