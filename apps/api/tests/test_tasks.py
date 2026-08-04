"""Integration tests for the Tasks API (SPEC.md §12.1 LOW_WRITE -- tasks run
without an approval gate). No real DB: the tasks repository dependency is
swapped for an in-memory fake, mirroring test_projects.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.main import app
from personal_ai_api.tasks_repository import TaskNotFound, TaskRecord, get_tasks_repository


class FakeTasksRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskRecord] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"task-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_task(self, user_id, title, description, project_id, due_at) -> TaskRecord:
        record = TaskRecord(
            id=self._new_id(),
            project_id=project_id,
            title=title,
            description=description,
            status="open",
            due_at=due_at.isoformat() if due_at else None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        self.tasks[record.id] = record
        return record

    async def list_tasks(self, user_id, project_id=None, status=None) -> list[TaskRecord]:
        results = list(self.tasks.values())
        if project_id:
            results = [t for t in results if t.project_id == project_id]
        if status:
            results = [t for t in results if t.status == status]
        return results

    async def update_task(self, task_id, user_id, updates) -> TaskRecord:
        if task_id not in self.tasks:
            raise TaskNotFound(task_id)
        current = self.tasks[task_id]
        merged = {**vars(current), **updates}
        if "due_at" in updates and updates["due_at"] is not None:
            merged["due_at"] = updates["due_at"].isoformat()
        record = TaskRecord(**merged)
        self.tasks[task_id] = record
        return record


@pytest.fixture
def repository():
    return FakeTasksRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_tasks_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_task_returns_201_and_defaults_to_open(client: TestClient) -> None:
    response = client.post("/api/v1/tasks", json={"title": "Write tests"})

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Write tests"
    assert body["status"] == "open"
    assert body["description"] is None
    assert body["due_at"] is None
    assert "id" in body


def test_create_task_with_all_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={
            "title": "Ship phase 5",
            "description": "Approvals + tasks API",
            "project_id": "proj-1",
            "due_at": "2026-08-10T00:00:00+00:00",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == "proj-1"
    assert body["description"] == "Approvals + tasks API"
    assert body["due_at"] is not None


def test_list_tasks_returns_created_tasks(client: TestClient) -> None:
    client.post("/api/v1/tasks", json={"title": "One"})
    client.post("/api/v1/tasks", json={"title": "Two"})

    response = client.get("/api/v1/tasks")

    assert response.status_code == 200
    titles = {t["title"] for t in response.json()}
    assert titles == {"One", "Two"}


def test_list_tasks_filters_by_project_id(client: TestClient) -> None:
    client.post("/api/v1/tasks", json={"title": "In project", "project_id": "proj-1"})
    client.post("/api/v1/tasks", json={"title": "No project"})

    response = client.get("/api/v1/tasks", params={"project_id": "proj-1"})

    assert response.status_code == 200
    titles = {t["title"] for t in response.json()}
    assert titles == {"In project"}


def test_list_tasks_filters_by_status(client: TestClient) -> None:
    created = client.post("/api/v1/tasks", json={"title": "Done soon"}).json()
    client.patch(f"/api/v1/tasks/{created['id']}", json={"status": "done"})
    client.post("/api/v1/tasks", json={"title": "Still open"})

    response = client.get("/api/v1/tasks", params={"status": "done"})

    assert response.status_code == 200
    titles = {t["title"] for t in response.json()}
    assert titles == {"Done soon"}


def test_patch_task_partially_updates_fields(client: TestClient) -> None:
    created = client.post(
        "/api/v1/tasks", json={"title": "Original", "description": "Original desc"}
    ).json()

    response = client.patch(f"/api/v1/tasks/{created['id']}", json={"status": "done"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["title"] == "Original"
    assert body["description"] == "Original desc"


def test_patch_unknown_task_returns_404(client: TestClient) -> None:
    response = client.patch("/api/v1/tasks/does-not-exist", json={"title": "x"})

    assert response.status_code == 404
