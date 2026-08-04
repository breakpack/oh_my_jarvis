"""Projects API (SPEC.md §15 Projects, §2.1 project-scoped conversations)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from personal_ai_api.projects_repository import (
    ProjectNotFound,
    ProjectsRepository,
    get_projects_repository,
)

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str
    created_at: str
    updated_at: str


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    repository: ProjectsRepository = Depends(get_projects_repository),
) -> ProjectOut:
    user_id = await repository.get_or_create_default_user()
    project = await repository.create_project(user_id, payload.name, payload.description)
    return ProjectOut(**vars(project))


@router.get("/projects")
async def list_projects(
    repository: ProjectsRepository = Depends(get_projects_repository),
) -> list[ProjectOut]:
    user_id = await repository.get_or_create_default_user()
    projects = await repository.list_projects(user_id)
    return [ProjectOut(**vars(p)) for p in projects]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    repository: ProjectsRepository = Depends(get_projects_repository),
) -> ProjectOut:
    user_id = await repository.get_or_create_default_user()
    try:
        project = await repository.get_project(project_id, user_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return ProjectOut(**vars(project))


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    repository: ProjectsRepository = Depends(get_projects_repository),
) -> ProjectOut:
    user_id = await repository.get_or_create_default_user()
    updates = payload.model_dump(exclude_unset=True)
    try:
        project = await repository.update_project(project_id, user_id, updates)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return ProjectOut(**vars(project))
