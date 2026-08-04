"""Tasks API (SPEC.md §12.1: tasks are LOW_WRITE, so they run without an
approval gate -- contrast with skills.py's medium+/high risk actions)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from personal_ai_api.tasks_repository import TaskNotFound, TasksRepository, get_tasks_repository

router = APIRouter(prefix="/api/v1", tags=["tasks"])


def _naive_utc(value: datetime | None) -> datetime | None:
    """DB columns are TIMESTAMP WITHOUT TIME ZONE; strip any incoming tzinfo (UTC by convention)."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    project_id: str | None = None
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    id: str
    project_id: str | None = None
    title: str
    description: str | None = None
    status: str
    due_at: str | None = None
    created_at: str
    updated_at: str


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    repository: TasksRepository = Depends(get_tasks_repository),
) -> TaskOut:
    user_id = await repository.get_or_create_default_user()
    task = await repository.create_task(
        user_id, payload.title, payload.description, payload.project_id, _naive_utc(payload.due_at)
    )
    return TaskOut(**vars(task))


@router.get("/tasks")
async def list_tasks(
    project_id: str | None = None,
    status: str | None = None,
    repository: TasksRepository = Depends(get_tasks_repository),
) -> list[TaskOut]:
    user_id = await repository.get_or_create_default_user()
    tasks = await repository.list_tasks(user_id, project_id=project_id, status=status)
    return [TaskOut(**vars(t)) for t in tasks]


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    repository: TasksRepository = Depends(get_tasks_repository),
) -> TaskOut:
    user_id = await repository.get_or_create_default_user()
    updates = payload.model_dump(exclude_unset=True)
    if "due_at" in updates:
        updates["due_at"] = _naive_utc(payload.due_at)
    try:
        task = await repository.update_task(task_id, user_id, updates)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return TaskOut(**vars(task))
