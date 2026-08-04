"""Memory API (SPEC.md §8 Memory, §15 Memory)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from personal_ai_api.memory_repository import (
    MemoryNotFound,
    MemoryRepository,
    get_memory_repository,
)

router = APIRouter(prefix="/api/v1", tags=["memory"])

# SPEC.md §8.3 memory write policy: low-confidence facts must not be persisted.
MIN_PERSISTABLE_CONFIDENCE = 0.5


class MemoryCreate(BaseModel):
    content: str
    project_id: str | None = None
    source: str = "manual"
    confidence: float = 1.0
    valid_until: datetime | None = None


class MemoryUpdate(BaseModel):
    content: str | None = None
    confidence: float | None = None
    valid_until: datetime | None = None


class MemorySearchRequest(BaseModel):
    query: str
    project_id: str | None = None


class MemoryOut(BaseModel):
    id: str
    project_id: str | None = None
    content: str
    source: str
    confidence: float
    valid_from: str | None = None
    valid_until: str | None = None
    created_at: str
    updated_at: str


def _reject_low_confidence(confidence: float) -> None:
    if confidence < MIN_PERSISTABLE_CONFIDENCE:
        raise HTTPException(status_code=422, detail="confidence too low to persist (<0.5)")


@router.get("/memories")
async def list_memories(
    project_id: str | None = None,
    query: str | None = None,
    repository: MemoryRepository = Depends(get_memory_repository),
) -> list[MemoryOut]:
    user_id = await repository.get_or_create_default_user()
    memories = await repository.list_memories(user_id, project_id=project_id, query=query)
    return [MemoryOut(**vars(m)) for m in memories]


@router.post("/memories", status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    repository: MemoryRepository = Depends(get_memory_repository),
) -> MemoryOut:
    _reject_low_confidence(payload.confidence)
    user_id = await repository.get_or_create_default_user()
    memory = await repository.create_memory(
        user_id=user_id,
        content=payload.content,
        project_id=payload.project_id,
        source=payload.source,
        confidence=payload.confidence,
        valid_until=payload.valid_until,
    )
    return MemoryOut(**vars(memory))


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    repository: MemoryRepository = Depends(get_memory_repository),
) -> MemoryOut:
    updates = payload.model_dump(exclude_unset=True)
    if "confidence" in updates:
        _reject_low_confidence(updates["confidence"])
    user_id = await repository.get_or_create_default_user()
    try:
        memory = await repository.update_memory(memory_id, user_id, updates)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc
    return MemoryOut(**vars(memory))


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    repository: MemoryRepository = Depends(get_memory_repository),
) -> None:
    user_id = await repository.get_or_create_default_user()
    try:
        await repository.delete_memory(memory_id, user_id)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail="Memory not found") from exc


@router.post("/memories/search")
async def search_memories(
    payload: MemorySearchRequest,
    repository: MemoryRepository = Depends(get_memory_repository),
) -> list[MemoryOut]:
    user_id = await repository.get_or_create_default_user()
    memories = await repository.list_memories(
        user_id, project_id=payload.project_id, query=payload.query
    )
    return [MemoryOut(**vars(m)) for m in memories]
