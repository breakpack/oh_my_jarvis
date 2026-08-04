"""Integration tests for the Knowledge search API (SPEC.md §15, §8.5, §21).
No real DB/Ollama: the knowledge repository dependency (which owns both the
pgvector and full-text queries) is swapped for an in-memory fake.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.db import get_default_user_id
from personal_ai_api.knowledge_repository import SearchResult, get_knowledge_repository
from personal_ai_api.main import app


class FakeKnowledgeRepository:
    def __init__(self) -> None:
        self.results: list[SearchResult] = []
        self.calls: list[dict] = []

    async def search(self, user_id, query, project_id=None, top_k=5) -> list[SearchResult]:
        self.calls.append(
            {"user_id": user_id, "query": query, "project_id": project_id, "top_k": top_k}
        )
        return self.results


@pytest.fixture
def repository():
    return FakeKnowledgeRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_knowledge_repository] = lambda: repository
    app.dependency_overrides[get_default_user_id] = lambda: "user-1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search_returns_results(client, repository):
    repository.results = [
        SearchResult(
            document_id="doc-1",
            document_title="Doc One",
            chunk_id="chunk-1",
            content="relevant content",
            page=2,
            section=None,
            score=0.75,
        )
    ]

    response = client.post("/api/v1/knowledge/search", json={"query": "foo"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "document_id": "doc-1",
            "document_title": "Doc One",
            "chunk_id": "chunk-1",
            "content": "relevant content",
            "page": 2,
            "section": None,
            "score": 0.75,
        }
    ]


def test_search_passes_project_id_and_top_k_through(client, repository):
    client.post(
        "/api/v1/knowledge/search",
        json={"query": "foo", "project_id": "proj-a", "top_k": 3},
    )

    assert repository.calls == [
        {"user_id": "user-1", "query": "foo", "project_id": "proj-a", "top_k": 3}
    ]


def test_search_defaults_top_k_to_five(client, repository):
    client.post("/api/v1/knowledge/search", json={"query": "foo"})

    assert repository.calls[0]["top_k"] == 5
    assert repository.calls[0]["project_id"] is None


def test_search_returns_empty_list_when_no_matches(client):
    response = client.post("/api/v1/knowledge/search", json={"query": "nothing matches"})

    assert response.status_code == 200
    assert response.json() == []
