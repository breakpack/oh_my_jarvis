"""TaskDeadlineSource: turns overdue/near-due Tasks into RawEvents
(SPEC.md §13 Observe stage).

Reuses tasks_repository.py's TasksRepository Protocol + SqlAlchemy
implementation rather than querying the Task table directly, so this
source stays swappable with a fake in tests the same way every apps/api
router already is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_ai.proactive.sources import RawEvent
from personal_ai_api.tasks_repository import TasksRepository, get_tasks_repository

DUE_SOON_WINDOW = timedelta(hours=24)

# Task.status has no fixed enum (SPEC leaves it free-form) -- these are the
# values pai task update/PATCH .../tasks/{id} realistically get set to for
# "this task is done, stop reminding me about it".
_COMPLETED_STATUSES = {"done", "completed", "cancelled", "closed"}


class TaskDeadlineSource:
    name = "task_deadline"

    def __init__(self, user_id: str, repository: TasksRepository | None = None) -> None:
        self._user_id = user_id
        self._repository = repository or get_tasks_repository()

    async def check(self) -> list[RawEvent]:
        now = datetime.now(UTC).replace(tzinfo=None)
        tasks = await self._repository.list_tasks(self._user_id)

        events: list[RawEvent] = []
        for task in tasks:
            if task.status.lower() in _COMPLETED_STATUSES:
                continue
            if task.due_at is None:
                continue

            due_at = datetime.fromisoformat(task.due_at)
            if due_at.tzinfo is not None:
                due_at = due_at.astimezone(UTC).replace(tzinfo=None)

            if due_at <= now:
                severity = "high"
                status_text = "마감이 지났습니다"
            elif due_at <= now + DUE_SOON_WINDOW:
                severity = "medium"
                status_text = "마감이 24시간 이내입니다"
            else:
                continue

            events.append(
                RawEvent(
                    source_type=self.name,
                    external_id=task.id,
                    title=f"Task 마감 임박: {task.title}",
                    body=f"{status_text} (마감: {due_at.isoformat()})",
                    severity=severity,
                )
            )
        return events
