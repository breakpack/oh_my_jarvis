import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_tasks_table,
    create_task,
    fetch_tasks,
    update_task,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


TASK = {
    "id": "t1",
    "title": "Write weekly report",
    "description": "",
    "project_id": "p1",
    "status": "open",
    "due_at": None,
    "created_at": "2026-08-04T00:00:00Z",
    "updated_at": "2026-08-04T00:00:00Z",
}


def test_fetch_tasks_sends_project_and_status_params() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([TASK]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = fetch_tasks(client, "http://testserver", "p1", "open")
    finally:
        client.close()

    assert result == [TASK]
    assert captured["params"] == {"project_id": "p1", "status": "open"}


def test_fetch_tasks_omits_filters_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        fetch_tasks(client, "http://testserver", None, None)
    finally:
        client.close()

    assert captured["params"] == {}


def test_build_tasks_table_row_count() -> None:
    table = build_tasks_table([TASK])
    assert table.row_count == 1


def test_fetch_tasks_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "database unavailable"})
    try:
        with pytest.raises(ApiError, match="database unavailable"):
            fetch_tasks(client, "http://testserver", None, None)
    finally:
        client.close()


def test_create_task_sends_title_description_and_project() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, content=json.dumps(TASK).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = create_task(client, "http://testserver", "Write weekly report", "details", "p1")
    finally:
        client.close()

    assert result == TASK
    assert captured["body"] == {
        "title": "Write weekly report",
        "description": "details",
        "project_id": "p1",
    }


def test_create_task_omits_optional_fields_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, content=json.dumps(TASK).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        create_task(client, "http://testserver", "Write weekly report", None, None)
    finally:
        client.close()

    assert captured["body"] == {"title": "Write weekly report"}


def test_create_task_raises_api_error_on_failure() -> None:
    client = _client(400, {"detail": "title is required"})
    try:
        with pytest.raises(ApiError, match="title is required"):
            create_task(client, "http://testserver", "", None, None)
    finally:
        client.close()


def test_update_task_sends_status_and_returns_task() -> None:
    captured: dict[str, object] = {}
    updated = {**TASK, "status": "done"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v1/tasks/t1"
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps(updated).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = update_task(client, "http://testserver", "t1", "done")
    finally:
        client.close()

    assert result == updated
    assert captured["body"] == {"status": "done"}


def test_update_task_raises_api_error_on_404() -> None:
    client = _client(404, {"detail": "task not found"})
    try:
        with pytest.raises(ApiError, match="task not found"):
            update_task(client, "http://testserver", "missing", "done")
    finally:
        client.close()
