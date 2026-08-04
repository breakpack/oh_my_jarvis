import json
from pathlib import Path

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_knowledge_table,
    ingest_document,
    search_knowledge,
)


def test_ingest_document_sends_multipart_file_and_returns_metadata(tmp_path: Path) -> None:
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake content")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content
        return httpx.Response(201, content=json.dumps({"id": "doc1", "chunk_count": 12}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = ingest_document(client, "http://testserver", file_path, "p1", "My Paper")
    finally:
        client.close()

    assert result == {"id": "doc1", "chunk_count": 12}
    assert "multipart/form-data" in str(captured["content_type"])
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"paper.pdf" in body
    assert b"My Paper" in body
    assert b"p1" in body


def test_ingest_document_raises_api_error_on_failure(tmp_path: Path) -> None:
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"data")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=json.dumps({"detail": "unsupported file type"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError, match="unsupported file type"):
            ingest_document(client, "http://testserver", file_path, None, None)
    finally:
        client.close()


def test_search_knowledge_returns_results_and_builds_table() -> None:
    results = [
        {
            "document_id": "doc1",
            "document_title": "Security Debt Report",
            "chunk_id": "c1",
            "content": "Security debt accumulates when patches are deferred.",
            "page": 3,
            "section": "Intro",
            "score": 0.87,
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(results).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = search_knowledge(client, "http://testserver", "security debt", None, None)
    finally:
        client.close()

    assert result == results
    table = build_knowledge_table(result)
    assert table.row_count == 1


def test_search_knowledge_sends_project_id_and_top_k() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=json.dumps([]).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        search_knowledge(client, "http://testserver", "kubernetes", "p1", 5)
    finally:
        client.close()

    assert captured["body"] == {"query": "kubernetes", "project_id": "p1", "top_k": 5}


def test_search_knowledge_raises_api_error_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=json.dumps({"detail": "project not found"}).encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApiError, match="project not found"):
            search_knowledge(client, "http://testserver", "x", "missing-project", None)
    finally:
        client.close()
