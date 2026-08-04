import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_memories_table,
    forget_memory,
    list_memories,
    search_memories,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


MEMORY = {
    "id": "m1",
    "content": "User prefers dark mode",
    "project_id": "p1",
    "source": "chat",
    "confidence": 0.9,
    "valid_until": None,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}


def test_search_memories_sends_query_and_project_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps([MEMORY]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = search_memories(client, "http://testserver", "Kubernetes", "p1")
    finally:
        client.close()

    assert result == [MEMORY]
    assert captured["body"] == {"query": "Kubernetes", "project_id": "p1"}
    table = build_memories_table(result)
    assert table.row_count == 1


def test_search_memories_omits_project_id_when_none() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps([]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        search_memories(client, "http://testserver", "Kubernetes", None)
    finally:
        client.close()

    assert captured["body"] == {"query": "Kubernetes"}


def test_search_memories_raises_api_error_on_failure() -> None:
    client = _client(404, {"detail": "project not found"})
    try:
        with pytest.raises(ApiError, match="project not found"):
            search_memories(client, "http://testserver", "x", "missing-project")
    finally:
        client.close()


def test_list_memories_passes_project_filter_as_query_param() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, content=json.dumps([MEMORY]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = list_memories(client, "http://testserver", "p1")
    finally:
        client.close()

    assert result == [MEMORY]
    assert captured["params"] == {"project_id": "p1"}


def test_forget_memory_success_no_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        forget_memory(client, "http://testserver", "m1")
    finally:
        client.close()


def test_forget_memory_raises_api_error_when_not_found() -> None:
    client = _client(404, {"detail": "memory not found"})
    try:
        with pytest.raises(ApiError, match="memory not found"):
            forget_memory(client, "http://testserver", "missing")
    finally:
        client.close()
