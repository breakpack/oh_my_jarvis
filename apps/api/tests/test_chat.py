"""Integration tests for the chat API (SPEC.md §21). No real DB or Ollama
network calls: the chat repository and model provider dependencies are
swapped for in-memory fakes.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from personal_ai_api.chat import get_model_provider
from personal_ai_api.chat_repository import (
    ConversationNotFound,
    ConversationRecord,
    MessageRecord,
    get_chat_repository,
)
from personal_ai_api.main import app

from personal_ai.models.providers import ModelProviderError


class FakeChatRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, ConversationRecord] = {}
        self.messages: dict[str, list[MessageRecord]] = {}
        self.audit: list[dict] = []
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def get_or_create_conversation(self, conversation_id, user_id) -> str:
        if conversation_id:
            if conversation_id not in self.conversations:
                raise ConversationNotFound(conversation_id)
            return conversation_id
        conv_id = self._new_id()
        self.conversations[conv_id] = ConversationRecord(
            id=conv_id,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
            preview=None,
        )
        self.messages[conv_id] = []
        return conv_id

    async def get_conversation(self, conversation_id, user_id) -> ConversationRecord:
        if conversation_id not in self.conversations:
            raise ConversationNotFound(conversation_id)
        return self.conversations[conversation_id]

    async def add_message(self, conversation_id, role, content) -> MessageRecord:
        message = MessageRecord(
            id=self._new_id(), role=role, content=content, created_at="2026-01-01T00:00:00"
        )
        self.messages.setdefault(conversation_id, []).append(message)
        return message

    async def list_messages(self, conversation_id) -> list[MessageRecord]:
        return list(self.messages.get(conversation_id, []))

    async def list_conversations(self, user_id) -> list[ConversationRecord]:
        return list(self.conversations.values())

    async def record_audit(self, user_id, event_type, payload) -> None:
        self.audit.append({"user_id": user_id, "event_type": event_type, **payload})


class FakeOllamaProvider:
    model = "fake-model"
    provider_name = "ollama"

    async def generate(self, request):  # pragma: no cover - not exercised by these tests
        raise NotImplementedError

    async def stream(self, request):
        for chunk in ["Hello", ", ", "world!"]:
            yield chunk


class FailingOllamaProvider:
    model = "fake-model"
    provider_name = "ollama"

    async def generate(self, request):  # pragma: no cover - not exercised by these tests
        raise NotImplementedError

    async def stream(self, request):
        if False:
            yield ""  # pragma: no cover - makes this an async generator function
        raise ModelProviderError("Could not reach Ollama at http://fake-ollama. Is it running?")


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        lines = block.splitlines()
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((event, data))
    return events


def _done_event(text: str) -> dict:
    return next(data for event, data in _parse_sse(text) if event == "done")


@pytest.fixture
def repository():
    return FakeChatRepository()


@pytest.fixture
def client(repository):
    app.dependency_overrides[get_chat_repository] = lambda: repository
    app.dependency_overrides[get_model_provider] = lambda: FakeOllamaProvider()
    yield TestClient(app)
    app.dependency_overrides.clear()


async def test_chat_creates_conversation_streams_tokens_and_persists_messages(client, repository):
    response = client.post("/api/v1/chat", json={"conversation_id": None, "message": "hi"})

    assert response.status_code == 200
    events = _parse_sse(response.text)

    token_events = [data["delta"] for event, data in events if event == "token"]
    assert "".join(token_events) == "Hello, world!"

    done = _done_event(response.text)
    assert done["provider"] == "ollama"
    assert done["model"] == "fake-model"
    conversation_id = done["conversation_id"]

    stored = await repository.list_messages(conversation_id)
    assert [(m.role, m.content) for m in stored] == [
        ("user", "hi"),
        ("assistant", "Hello, world!"),
    ]

    assert len(repository.audit) == 1
    audit_entry = repository.audit[0]
    assert audit_entry["event_type"] == "chat"
    assert audit_entry["success"] is True
    assert audit_entry["user_message_chars"] == len("hi")
    assert audit_entry["assistant_message_chars"] == len("Hello, world!")
    # SPEC.md §20.4: raw message bodies must never be written to the audit log.
    assert "hi" not in json.dumps(audit_entry)
    assert "Hello, world!" not in json.dumps(audit_entry)


async def test_chat_reuses_existing_conversation(client, repository):
    first = client.post("/api/v1/chat", json={"conversation_id": None, "message": "first"})
    conversation_id = _done_event(first.text)["conversation_id"]

    second = client.post(
        "/api/v1/chat", json={"conversation_id": conversation_id, "message": "second"}
    )
    assert second.status_code == 200

    stored = await repository.list_messages(conversation_id)
    assert [m.content for m in stored] == ["first", "Hello, world!", "second", "Hello, world!"]


def test_chat_unknown_conversation_id_returns_404(client):
    response = client.post(
        "/api/v1/chat", json={"conversation_id": "does-not-exist", "message": "hi"}
    )

    assert response.status_code == 404


async def test_chat_reports_ollama_failure_as_sse_error(client, repository):
    app.dependency_overrides[get_model_provider] = lambda: FailingOllamaProvider()

    response = client.post("/api/v1/chat", json={"conversation_id": None, "message": "hi"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "error"
    assert "ollama" in events[0][1]["error"].lower()
    assert not any(event == "done" for event, _ in events)

    conversation_id = next(iter(repository.conversations))
    stored = await repository.list_messages(conversation_id)
    assert [m.role for m in stored] == ["user"]

    assert repository.audit[-1]["success"] is False
    assert repository.audit[-1]["error"]


def test_list_and_get_conversation(client):
    create = client.post("/api/v1/chat", json={"conversation_id": None, "message": "hello"})
    conversation_id = _done_event(create.text)["conversation_id"]

    listing = client.get("/api/v1/conversations")
    assert listing.status_code == 200
    ids = [c["id"] for c in listing.json()]
    assert conversation_id in ids

    detail = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail.status_code == 200
    roles = [m["role"] for m in detail.json()]
    assert roles == ["user", "assistant"]


def test_get_unknown_conversation_returns_404(client):
    response = client.get("/api/v1/conversations/does-not-exist")

    assert response.status_code == 404
