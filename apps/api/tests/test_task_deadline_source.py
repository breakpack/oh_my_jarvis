"""Unit tests for TaskDeadlineSource (SPEC.md §13 Observe stage). Verified
against a fake TasksRepository -- no real DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from personal_ai_api.proactive.task_deadline_source import TaskDeadlineSource
from personal_ai_api.tasks_repository import TaskRecord

# TaskDeadlineSource.check() compares against the real wall-clock time
# internally, so tests anchor to it too rather than a fixed calendar date.
NOW = datetime.now(UTC).replace(tzinfo=None)


def _task(**overrides: Any) -> TaskRecord:
    defaults: dict[str, Any] = dict(
        id="task-1",
        project_id=None,
        title="Ship the report",
        description=None,
        status="open",
        due_at=None,
        created_at="2026-08-01T00:00:00",
        updated_at="2026-08-01T00:00:00",
    )
    defaults.update(overrides)
    return TaskRecord(**defaults)


class FakeTasksRepository:
    def __init__(self, tasks: list[TaskRecord]) -> None:
        self.tasks = tasks
        self.calls: list[str] = []

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_task(self, *args, **kwargs) -> TaskRecord:
        raise NotImplementedError

    async def list_tasks(self, user_id, project_id=None, status=None) -> list[TaskRecord]:
        self.calls.append(user_id)
        return self.tasks

    async def update_task(self, *args, **kwargs) -> TaskRecord:
        raise NotImplementedError


async def test_overdue_task_becomes_high_severity_event() -> None:
    overdue = _task(id="t-overdue", due_at=(NOW - timedelta(hours=1)).isoformat())
    repository = FakeTasksRepository([overdue])
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    assert len(events) == 1
    event = events[0]
    assert event.source_type == "task_deadline"
    assert event.external_id == "t-overdue"
    assert event.severity == "high"
    assert "Ship the report" in event.title


async def test_task_due_within_24h_becomes_medium_severity_event() -> None:
    due_soon = _task(id="t-soon", due_at=(NOW + timedelta(hours=6)).isoformat())
    repository = FakeTasksRepository([due_soon])
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    assert len(events) == 1
    assert events[0].severity == "medium"


async def test_task_due_far_in_the_future_is_ignored() -> None:
    far_future = _task(id="t-later", due_at=(NOW + timedelta(days=5)).isoformat())
    repository = FakeTasksRepository([far_future])
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    assert events == []


async def test_task_with_no_due_at_is_ignored() -> None:
    repository = FakeTasksRepository([_task(id="t-no-due", due_at=None)])
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    assert events == []


@pytest.mark.parametrize("status", ["done", "completed", "cancelled", "closed", "DONE"])
async def test_completed_overdue_task_is_ignored(status: str) -> None:
    completed = _task(id="t-done", status=status, due_at=(NOW - timedelta(hours=1)).isoformat())
    repository = FakeTasksRepository([completed])
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    assert events == []


async def test_check_passes_user_id_through_to_the_repository() -> None:
    repository = FakeTasksRepository([])
    source = TaskDeadlineSource("user-42", repository)

    await source.check()

    assert repository.calls == ["user-42"]


async def test_multiple_tasks_are_all_evaluated_independently() -> None:
    tasks = [
        _task(id="overdue", due_at=(NOW - timedelta(minutes=5)).isoformat()),
        _task(id="soon", due_at=(NOW + timedelta(hours=1)).isoformat()),
        _task(id="later", due_at=(NOW + timedelta(days=10)).isoformat()),
        _task(id="done", status="done", due_at=(NOW - timedelta(hours=1)).isoformat()),
    ]
    repository = FakeTasksRepository(tasks)
    source = TaskDeadlineSource("user-1", repository)

    events = await source.check()

    external_ids = {e.external_id: e.severity for e in events}
    assert external_ids == {"overdue": "high", "soon": "medium"}
