"""Knowledge search API (SPEC.md §15 Knowledge, §8.5 hybrid retrieval)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from personal_ai_api.db import get_default_user_id
from personal_ai_api.knowledge_repository import (
    KnowledgeRepository,
    get_knowledge_repository,
)

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


class KnowledgeSearchRequest(BaseModel):
    query: str
    project_id: str | None = None
    top_k: int = 5


class KnowledgeSearchResult(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    content: str
    page: int | None = None
    section: str | None = None
    score: float


@router.post("/knowledge/search")
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    user_id: str = Depends(get_default_user_id),
    repository: KnowledgeRepository = Depends(get_knowledge_repository),
) -> list[KnowledgeSearchResult]:
    results = await repository.search(
        user_id, payload.query, project_id=payload.project_id, top_k=payload.top_k
    )
    return [KnowledgeSearchResult(**vars(r)) for r in results]
