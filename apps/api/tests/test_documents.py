"""Integration tests for the Documents API (SPEC.md §15 Knowledge, §21).
No real DB/Ollama: the documents repository dependency is swapped for an
in-memory fake, so `ingest_document`'s parse/chunk/embed pipeline itself is
never exercised here (see test_knowledge_chunker.py / test_knowledge_parsers.py
for that, with Ollama embedding calls mocked).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.documents_repository import (
    DocumentNotFound,
    DocumentRecord,
    get_documents_repository,
)
from personal_ai_api.main import app


class FakeDocumentsRepository:
    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self._counter = 0
        self.next_ingest_error: Exception | None = None

    def _new_id(self) -> str:
        self._counter += 1
        return f"doc-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def ingest(self, user_id, project_id, title, filename, raw) -> DocumentRecord:
        if self.next_ingest_error is not None:
            error, self.next_ingest_error = self.next_ingest_error, None
            raise error
        record = DocumentRecord(
            id=self._new_id(),
            title=title,
            source_type="text",
            project_id=project_id,
            status="ready",
            chunk_count=3,
            created_at="2026-01-01T00:00:00",
        )
        self.documents[record.id] = record
        return record

    async def list_documents(self, user_id, project_id=None) -> list[DocumentRecord]:
        items = list(self.documents.values())
        if project_id:
            items = [d for d in items if d.project_id == project_id]
        return items

    async def get_document(self, document_id, user_id) -> DocumentRecord:
        if document_id not in self.documents:
            raise DocumentNotFound(document_id)
        return self.documents[document_id]

    async def delete_document(self, document_id, user_id) -> None:
        if document_id not in self.documents:
            raise DocumentNotFound(document_id)
        del self.documents[document_id]


@pytest.fixture
def repository():
    return FakeDocumentsRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_documents_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_upload_document_returns_201(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"title": "My Notes"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "My Notes"
    assert body["status"] == "ready"
    assert body["chunk_count"] == 3
    assert "content" not in body  # metadata only, never full chunk text


def test_upload_document_uses_filename_when_title_omitted(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("report.md", b"# Report", "text/markdown")},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "report.md"


def test_upload_document_ingestion_failure_returns_422(client, repository):
    repository.next_ingest_error = ValueError("No extractable text found in the uploaded document.")

    response = client.post(
        "/api/v1/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No extractable text found in the uploaded document."
    assert not repository.documents


def test_list_documents_filters_by_project_id(client):
    client.post(
        "/api/v1/documents",
        files={"file": ("a.txt", b"a", "text/plain")},
        data={"project_id": "proj-a"},
    )
    client.post("/api/v1/documents", files={"file": ("b.txt", b"b", "text/plain")})

    response = client.get("/api/v1/documents", params={"project_id": "proj-a"})

    assert response.status_code == 200
    titles = [d["title"] for d in response.json()]
    assert titles == ["a.txt"]


def test_get_document_returns_metadata(client):
    created = client.post("/api/v1/documents", files={"file": ("a.txt", b"a", "text/plain")}).json()

    response = client.get(f"/api/v1/documents/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_document_returns_404(client):
    response = client.get("/api/v1/documents/does-not-exist")

    assert response.status_code == 404


def test_delete_document_returns_204(client, repository):
    created = client.post("/api/v1/documents", files={"file": ("a.txt", b"a", "text/plain")}).json()

    response = client.delete(f"/api/v1/documents/{created['id']}")

    assert response.status_code == 204
    assert created["id"] not in repository.documents


def test_delete_unknown_document_returns_404(client):
    response = client.delete("/api/v1/documents/does-not-exist")

    assert response.status_code == 404
