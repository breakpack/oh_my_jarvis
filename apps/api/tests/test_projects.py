"""Integration tests for the Projects API (SPEC.md §15, §21). No real DB:
the projects repository dependency is swapped for an in-memory fake.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.main import app
from personal_ai_api.projects_repository import (
    ProjectNotFound,
    ProjectRecord,
    get_projects_repository,
)


class FakeProjectsRepository:
    def __init__(self) -> None:
        self.projects: dict[str, ProjectRecord] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"proj-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_project(self, user_id, name, description) -> ProjectRecord:
        record = ProjectRecord(
            id=self._new_id(),
            name=name,
            description=description,
            status="active",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        self.projects[record.id] = record
        return record

    async def list_projects(self, user_id) -> list[ProjectRecord]:
        return list(self.projects.values())

    async def get_project(self, project_id, user_id) -> ProjectRecord:
        if project_id not in self.projects:
            raise ProjectNotFound(project_id)
        return self.projects[project_id]

    async def update_project(self, project_id, user_id, updates) -> ProjectRecord:
        if project_id not in self.projects:
            raise ProjectNotFound(project_id)
        record = ProjectRecord(**{**vars(self.projects[project_id]), **updates})
        self.projects[project_id] = record
        return record


@pytest.fixture
def repository():
    return FakeProjectsRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_projects_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_project_returns_201(client):
    response = client.post(
        "/api/v1/projects", json={"name": "Second Brain", "description": "RAG project"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Second Brain"
    assert body["description"] == "RAG project"
    assert body["status"] == "active"
    assert "id" in body


def test_create_project_without_description(client):
    response = client.post("/api/v1/projects", json={"name": "No description"})

    assert response.status_code == 201
    assert response.json()["description"] is None


def test_list_projects_returns_created_projects(client):
    client.post("/api/v1/projects", json={"name": "One"})
    client.post("/api/v1/projects", json={"name": "Two"})

    response = client.get("/api/v1/projects")

    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert names == {"One", "Two"}


def test_get_project_returns_created_project(client):
    created = client.post("/api/v1/projects", json={"name": "Solo"}).json()

    response = client.get(f"/api/v1/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_project_returns_404(client):
    response = client.get("/api/v1/projects/does-not-exist")

    assert response.status_code == 404


def test_patch_project_partially_updates_fields(client):
    created = client.post(
        "/api/v1/projects", json={"name": "Original", "description": "Original desc"}
    ).json()

    response = client.patch(f"/api/v1/projects/{created['id']}", json={"status": "archived"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "archived"
    # Fields not present in the PATCH body must be left untouched.
    assert body["name"] == "Original"
    assert body["description"] == "Original desc"


def test_patch_project_can_clear_description(client):
    created = client.post(
        "/api/v1/projects", json={"name": "Original", "description": "Original desc"}
    ).json()

    response = client.patch(f"/api/v1/projects/{created['id']}", json={"description": None})

    assert response.status_code == 200
    assert response.json()["description"] is None


def test_patch_unknown_project_returns_404(client):
    response = client.patch("/api/v1/projects/does-not-exist", json={"name": "x"})

    assert response.status_code == 404
