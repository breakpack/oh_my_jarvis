"""Documents API (SPEC.md §15 Knowledge, §2.3 RAG/Second Brain)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from personal_ai_api.documents_repository import (
    DocumentNotFound,
    DocumentsRepository,
    get_documents_repository,
)

router = APIRouter(prefix="/api/v1", tags=["documents"])


class DocumentOut(BaseModel):
    id: str
    title: str
    source_type: str
    project_id: str | None = None
    status: str
    chunk_count: int
    created_at: str


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    title: str | None = Form(None),
    project_id: str | None = Form(None),
    repository: DocumentsRepository = Depends(get_documents_repository),
) -> DocumentOut:
    user_id = await repository.get_or_create_default_user()
    raw = await file.read()
    filename = file.filename or "upload"
    try:
        document = await repository.ingest(
            user_id=user_id,
            project_id=project_id,
            title=title or filename,
            filename=filename,
            raw=raw,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DocumentOut(**vars(document))


@router.get("/documents")
async def list_documents(
    project_id: str | None = None,
    repository: DocumentsRepository = Depends(get_documents_repository),
) -> list[DocumentOut]:
    user_id = await repository.get_or_create_default_user()
    documents = await repository.list_documents(user_id, project_id=project_id)
    return [DocumentOut(**vars(d)) for d in documents]


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    repository: DocumentsRepository = Depends(get_documents_repository),
) -> DocumentOut:
    user_id = await repository.get_or_create_default_user()
    try:
        document = await repository.get_document(document_id, user_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    return DocumentOut(**vars(document))


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    repository: DocumentsRepository = Depends(get_documents_repository),
) -> None:
    user_id = await repository.get_or_create_default_user()
    try:
        await repository.delete_document(document_id, user_id)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
