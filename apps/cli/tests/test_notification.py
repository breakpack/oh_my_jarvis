import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_notifications_table,
    check_now_notifications,
    dismiss_notification,
    fetch_notifications,
    mark_notification_seen,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


NOTIFICATION = {
    "id": "n1",
    "source_type": "github_ci",
    "title": "CI failed on main",
    "body": "3 checks failed",
    "priority": "high",
    "status": "unseen",
    "created_at": "2026-08-04T00:00:00Z",
}


def test_fetch_notifications_sends_status_param() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([NOTIFICATION]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_notifications(client, "http://testserver", "unseen")
    finally:
        client.close()

    assert result == [NOTIFICATION]
    assert captured["path"] == "/api/v1/notifications"
    assert captured["params"] == {"status": "unseen"}


def test_fetch_notifications_omits_status_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        fetch_notifications(client, "http://testserver", None)
    finally:
        client.close()

    assert captured["params"] == {}


def test_fetch_notifications_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "notification service unavailable"})
    try:
        with pytest.raises(ApiError, match="notification service unavailable"):
            fetch_notifications(client, "http://testserver", None)
    finally:
        client.close()


def test_build_notifications_table_includes_high_priority_row() -> None:
    low = {**NOTIFICATION, "id": "n2", "priority": "low"}
    table = build_notifications_table([NOTIFICATION, low])
    assert table.row_count == 2


def test_mark_notification_seen_posts_to_seen_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/notifications/n1/seen"
        return httpx.Response(200, content=json.dumps({**NOTIFICATION, "status": "seen"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = mark_notification_seen(client, "http://testserver", "n1")
    finally:
        client.close()

    assert result["status"] == "seen"


def test_mark_notification_seen_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "notification not found"})
    try:
        with pytest.raises(ApiError, match="notification not found"):
            mark_notification_seen(client, "http://testserver", "missing-id")
    finally:
        client.close()


def test_dismiss_notification_posts_to_dismiss_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/notifications/n1/dismiss"
        return httpx.Response(
            200, content=json.dumps({**NOTIFICATION, "status": "dismissed"}).encode()
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = dismiss_notification(client, "http://testserver", "n1")
    finally:
        client.close()

    assert result["status"] == "dismissed"


def test_dismiss_notification_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "notification not found"})
    try:
        with pytest.raises(ApiError, match="notification not found"):
            dismiss_notification(client, "http://testserver", "missing-id")
    finally:
        client.close()


def test_check_now_notifications_returns_new_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/notifications/check-now"
        return httpx.Response(200, content=json.dumps([NOTIFICATION]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = check_now_notifications(client, "http://testserver")
    finally:
        client.close()

    assert result == [NOTIFICATION]


def test_check_now_notifications_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "check failed"})
    try:
        with pytest.raises(ApiError, match="check failed"):
            check_now_notifications(client, "http://testserver")
    finally:
        client.close()
