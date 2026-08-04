"""Integration tests for the Memory API (SPEC.md §8, §15, §21), including the
§8.3 low-confidence write policy. No real DB: the memory repository
dependency is swapped for an in-memory fake.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.main import app
from personal_ai_api.memory_repository import (
    MemoryNotFound,
    MemoryRecord,
    get_memory_repository,
)


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.memories: dict[str, MemoryRecord] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"mem-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_memory(
        self, user_id, content, project_id, source, confidence, valid_until
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=self._new_id(),
            project_id=project_id,
            content=content,
            source=source,
            confidence=confidence,
            valid_from=None,
            valid_until=valid_until.isoformat()
            if isinstance(valid_until, datetime)
            else valid_until,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        self.memories[record.id] = record
        return record

    async def list_memories(self, user_id, project_id=None, query=None) -> list[MemoryRecord]:
        items = list(self.memories.values())
        if project_id:
            items = [m for m in items if m.project_id == project_id]
        if query:
            items = [m for m in items if query.lower() in m.content.lower()]
        return items

    async def update_memory(self, memory_id, user_id, updates) -> MemoryRecord:
        if memory_id not in self.memories:
            raise MemoryNotFound(memory_id)
        normalized = {
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in updates.items()
        }
        record = MemoryRecord(**{**vars(self.memories[memory_id]), **normalized})
        self.memories[memory_id] = record
        return record

    async def delete_memory(self, memory_id, user_id) -> None:
        if memory_id not in self.memories:
            raise MemoryNotFound(memory_id)
        del self.memories[memory_id]

    async def delete_memories_by_content(self, user_id, project_id, query) -> int:
        matches = [
            memory_id
            for memory_id, memory in self.memories.items()
            if query.lower() in memory.content.lower()
            and (project_id is None or memory.project_id == project_id)
        ]
        for memory_id in matches:
            del self.memories[memory_id]
        return len(matches)


@pytest.fixture
def repository():
    return FakeMemoryRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_memory_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_memory_returns_201(client):
    response = client.post("/api/v1/memories", json={"content": "User likes dark roast coffee"})

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "User likes dark roast coffee"
    assert body["source"] == "manual"
    assert body["confidence"] == 1.0


def test_create_memory_below_confidence_floor_is_rejected(client, repository):
    response = client.post("/api/v1/memories", json={"content": "maybe true", "confidence": 0.3})

    assert response.status_code == 422
    assert response.json()["detail"] == "confidence too low to persist (<0.5)"
    assert not repository.memories


def test_create_memory_at_confidence_floor_is_persisted(client):
    response = client.post("/api/v1/memories", json={"content": "borderline", "confidence": 0.5})

    assert response.status_code == 201


def test_list_memories_filters_by_query(client):
    client.post("/api/v1/memories", json={"content": "loves espresso"})
    client.post("/api/v1/memories", json={"content": "hates decaf"})

    response = client.get("/api/v1/memories", params={"query": "espresso"})

    assert response.status_code == 200
    contents = [m["content"] for m in response.json()]
    assert contents == ["loves espresso"]


def test_list_memories_filters_by_project_id(client):
    client.post("/api/v1/memories", json={"content": "in project", "project_id": "proj-a"})
    client.post("/api/v1/memories", json={"content": "no project"})

    response = client.get("/api/v1/memories", params={"project_id": "proj-a"})

    assert response.status_code == 200
    contents = [m["content"] for m in response.json()]
    assert contents == ["in project"]


def test_search_memories_matches_get_list_semantics(client):
    client.post("/api/v1/memories", json={"content": "loves espresso"})
    client.post("/api/v1/memories", json={"content": "hates decaf"})

    response = client.post("/api/v1/memories/search", json={"query": "decaf"})

    assert response.status_code == 200
    contents = [m["content"] for m in response.json()]
    assert contents == ["hates decaf"]


def test_patch_memory_updates_content(client):
    created = client.post("/api/v1/memories", json={"content": "old fact"}).json()

    response = client.patch(f"/api/v1/memories/{created['id']}", json={"content": "new fact"})

    assert response.status_code == 200
    assert response.json()["content"] == "new fact"


def test_patch_memory_below_confidence_floor_is_rejected(client):
    created = client.post("/api/v1/memories", json={"content": "a fact"}).json()

    response = client.patch(f"/api/v1/memories/{created['id']}", json={"confidence": 0.1})

    assert response.status_code == 422
    assert response.json()["detail"] == "confidence too low to persist (<0.5)"


def test_patch_unknown_memory_returns_404(client):
    response = client.patch("/api/v1/memories/does-not-exist", json={"content": "x"})

    assert response.status_code == 404


def test_delete_memory_returns_204(client, repository):
    created = client.post("/api/v1/memories", json={"content": "temp fact"}).json()

    response = client.delete(f"/api/v1/memories/{created['id']}")

    assert response.status_code == 204
    assert created["id"] not in repository.memories


def test_delete_unknown_memory_returns_404(client):
    response = client.delete("/api/v1/memories/does-not-exist")

    assert response.status_code == 404
