import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_projects_table,
    create_project,
    fetch_projects,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_projects_returns_list() -> None:
    projects = [
        {
            "id": "p1",
            "name": "Kubernetes Migration",
            "description": "",
            "status": "active",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    ]
    client = _client(200, projects)
    try:
        result = fetch_projects(client, "http://testserver")
    finally:
        client.close()

    assert result == projects
    table = build_projects_table(result)
    assert table.row_count == 1


def test_fetch_projects_raises_api_error_on_failure() -> None:
    client = _client(500, {"detail": "database unavailable"})
    try:
        with pytest.raises(ApiError, match="database unavailable"):
            fetch_projects(client, "http://testserver")
    finally:
        client.close()


def test_create_project_sends_name_and_description_returns_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, content=json.dumps({"id": "p2", "name": "New"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = create_project(client, "http://testserver", "New", "a description")
    finally:
        client.close()

    assert result["id"] == "p2"
    assert captured["body"] == {"name": "New", "description": "a description"}


def test_create_project_raises_api_error_on_conflict() -> None:
    client = _client(409, {"detail": "project already exists"})
    try:
        with pytest.raises(ApiError, match="project already exists"):
            create_project(client, "http://testserver", "Dup", None)
    finally:
        client.close()


def test_build_projects_table_empty() -> None:
    table = build_projects_table([])
    assert table.row_count == 0
