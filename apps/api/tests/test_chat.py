"""Integration tests for the chat API (SPEC.md §21). No real DB or Ollama
network calls: the chat/memory repositories and model provider dependencies
are swapped for in-memory fakes.
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
from personal_ai_api.memory_repository import (
    MemoryNotFound,
    MemoryRecord,
    get_memory_repository,
)

from personal_ai.models.providers import ModelProviderError, ModelResponse


class FakeChatRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, ConversationRecord] = {}
        self.messages: dict[str, list[MessageRecord]] = {}
        self.summaries: dict[str, str] = {}
        self.audit: list[dict] = []
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def get_or_create_conversation(self, conversation_id, user_id, project_id=None) -> str:
        if conversation_id:
            if conversation_id not in self.conversations:
                raise ConversationNotFound(conversation_id)
            return conversation_id
        conv_id = self._new_id()
        self.conversations[conv_id] = ConversationRecord(
            id=conv_id,
            project_id=project_id,
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

    async def list_conversations(self, user_id, project_id=None) -> list[ConversationRecord]:
        items = list(self.conversations.values())
        if project_id:
            items = [c for c in items if c.project_id == project_id]
        return items

    async def get_conversation_summary(self, conversation_id) -> str | None:
        return self.summaries.get(conversation_id)

    async def upsert_conversation_summary(self, conversation_id, summary) -> None:
        self.summaries[conversation_id] = summary

    async def record_audit(self, user_id, event_type, payload) -> None:
        self.audit.append({"user_id": user_id, "event_type": event_type, **payload})


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.memories: dict[str, MemoryRecord] = {}
        self._counter = 0

    def _new_id(self) -> str:
        self._counter += 1
        return f"mem-{self._counter}"

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def create_memory(
        self, user_id, content, project_id, source, confidence, valid_until
    ) -> MemoryRecord:
        record = MemoryRecord(
            id=self._new_id(),
            project_id=project_id,
            content=content,
            source=source,
            confidence=confidence,
            valid_from=None,
            valid_until=valid_until.isoformat() if valid_until else None,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        self.memories[record.id] = record
        return record

    async def list_memories(self, user_id, project_id=None, query=None) -> list[MemoryRecord]:
        items = list(self.memories.values())
        if project_id:
            items = [m for m in items if m.project_id == project_id]
        if query:
            items = [m for m in items if query.lower() in m.content.lower()]
        return items

    async def update_memory(self, memory_id, user_id, updates) -> MemoryRecord:
        if memory_id not in self.memories:
            raise MemoryNotFound(memory_id)
        record = MemoryRecord(**{**vars(self.memories[memory_id]), **updates})
        self.memories[memory_id] = record
        return record

    async def delete_memory(self, memory_id, user_id) -> None:
        if memory_id not in self.memories:
            raise MemoryNotFound(memory_id)
        del self.memories[memory_id]

    async def delete_memories_by_content(self, user_id, project_id, query) -> int:
        matches = [
            memory_id
            for memory_id, memory in self.memories.items()
            if query.lower() in memory.content.lower()
            and (project_id is None or memory.project_id == project_id)
        ]
        for memory_id in matches:
            del self.memories[memory_id]
        return len(matches)


class FakeOllamaProvider:
    model = "fake-model"
    provider_name = "ollama"

    def __init__(self) -> None:
        self.last_request = None

    async def generate(self, request):
        return ModelResponse(
            content="요약된 대화 내용", model=self.model, provider=self.provider_name
        )

    async def stream(self, request):
        self.last_request = request
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


class UncallableProvider:
    """Fails the test if the chat command path ever falls through to Ollama."""

    model = "fake-model"
    provider_name = "ollama"

    async def generate(self, request):  # pragma: no cover
        raise AssertionError("provider.generate() should not be called for a chat command")

    async def stream(self, request):  # pragma: no cover
        raise AssertionError("provider.stream() should not be called for a chat command")
        yield ""  # pragma: no cover - makes this an async generator function


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
def memory_repository():
    return FakeMemoryRepository()


@pytest.fixture
def client(repository, memory_repository):
    app.dependency_overrides[get_chat_repository] = lambda: repository
    app.dependency_overrides[get_memory_repository] = lambda: memory_repository
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
    assert audit_entry["command"] is None
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


def test_chat_new_conversation_stores_project_id(client, repository):
    response = client.post(
        "/api/v1/chat",
        json={"conversation_id": None, "message": "hi", "project_id": "proj-a"},
    )
    conversation_id = _done_event(response.text)["conversation_id"]

    assert repository.conversations[conversation_id].project_id == "proj-a"


def test_list_conversations_filters_by_project_id(client, repository):
    with_project = client.post(
        "/api/v1/chat",
        json={"conversation_id": None, "message": "hi", "project_id": "proj-a"},
    )
    without_project = client.post("/api/v1/chat", json={"conversation_id": None, "message": "hi"})
    project_conv_id = _done_event(with_project.text)["conversation_id"]
    other_conv_id = _done_event(without_project.text)["conversation_id"]

    filtered = client.get("/api/v1/conversations", params={"project_id": "proj-a"})
    ids = [c["id"] for c in filtered.json()]
    assert ids == [project_conv_id]
    assert other_conv_id not in ids


def test_get_conversation_returns_detail_object_with_summary(client):
    create = client.post("/api/v1/chat", json={"conversation_id": None, "message": "hello"})
    conversation_id = _done_event(create.text)["conversation_id"]

    detail = client.get(f"/api/v1/conversations/{conversation_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == conversation_id
    assert body["summary"] is None
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


def test_get_unknown_conversation_returns_404(client):
    response = client.get("/api/v1/conversations/does-not-exist")

    assert response.status_code == 404


async def test_remember_command_persists_memory_without_calling_ollama(
    client, repository, memory_repository
):
    app.dependency_overrides[get_model_provider] = lambda: UncallableProvider()

    response = client.post(
        "/api/v1/chat", json={"conversation_id": None, "message": "/remember buy milk"}
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0] == ("token", {"delta": "✓ Remembered: buy milk"})
    done = _done_event(response.text)
    assert done["model"] == "system"
    assert done["provider"] == "command"

    [memory] = memory_repository.memories.values()
    assert memory.content == "buy milk"
    assert memory.source == "explicit_remember"
    assert memory.confidence == 1.0

    conversation_id = done["conversation_id"]
    stored = await repository.list_messages(conversation_id)
    assert [(m.role, m.content) for m in stored] == [
        ("user", "/remember buy milk"),
        ("assistant", "✓ Remembered: buy milk"),
    ]
    assert repository.audit[-1]["command"] == "remember"
    assert repository.audit[-1]["provider"] == "command"


def test_remember_without_content_returns_usage_hint(client, memory_repository):
    app.dependency_overrides[get_model_provider] = lambda: UncallableProvider()

    response = client.post("/api/v1/chat", json={"conversation_id": None, "message": "/remember"})

    events = _parse_sse(response.text)
    assert events[0] == ("token", {"delta": "사용법: /remember <내용>"})
    assert not memory_repository.memories


async def test_forget_command_deletes_matching_memories(client, memory_repository):
    app.dependency_overrides[get_model_provider] = lambda: UncallableProvider()

    remember = client.post(
        "/api/v1/chat", json={"conversation_id": None, "message": "/remember buy milk"}
    )
    conversation_id = _done_event(remember.text)["conversation_id"]
    assert len(memory_repository.memories) == 1

    forget = client.post(
        "/api/v1/chat",
        json={"conversation_id": conversation_id, "message": "/forget milk"},
    )

    events = _parse_sse(forget.text)
    assert events[0] == ("token", {"delta": "✓ Forgot 1 memory matching 'milk'."})
    assert not memory_repository.memories
    assert _done_event(forget.text)["provider"] == "command"


def test_forget_no_match_reports_zero_results(client):
    app.dependency_overrides[get_model_provider] = lambda: UncallableProvider()

    response = client.post(
        "/api/v1/chat", json={"conversation_id": None, "message": "/forget nonexistent"}
    )

    events = _parse_sse(response.text)
    assert events[0] == ("token", {"delta": "No matching memories found."})


def test_forget_without_query_does_not_wipe_all_memories(client, memory_repository):
    memory_repository.memories["mem-existing"] = MemoryRecord(
        id="mem-existing",
        project_id=None,
        content="do not delete me",
        source="manual",
        confidence=1.0,
        valid_from=None,
        valid_until=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    app.dependency_overrides[get_model_provider] = lambda: UncallableProvider()

    response = client.post("/api/v1/chat", json={"conversation_id": None, "message": "/forget"})

    events = _parse_sse(response.text)
    assert events[0] == ("token", {"delta": "사용법: /forget <검색어>"})
    assert "mem-existing" in memory_repository.memories


async def test_no_memory_command_sends_remainder_to_ollama(client, repository):
    response = client.post(
        "/api/v1/chat",
        json={"conversation_id": None, "message": "/no-memory what's the weather?"},
    )

    assert response.status_code == 200
    done = _done_event(response.text)
    assert done["provider"] == "ollama"
    conversation_id = done["conversation_id"]

    stored = await repository.list_messages(conversation_id)
    # The /no-memory prefix must not leak into the stored/forwarded chat message.
    assert stored[0].content == "what's the weather?"
    assert repository.audit[-1]["command"] == "no_memory"


async def test_summary_is_used_as_context_and_truncates_history(client, repository):
    conv_id = "conv-summary"
    repository.conversations[conv_id] = ConversationRecord(
        id=conv_id,
        project_id=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        preview=None,
    )
    repository.messages[conv_id] = [
        MessageRecord(
            id=f"old-{i}", role="user", content=f"old {i}", created_at="2026-01-01T00:00:00"
        )
        for i in range(20)
    ]
    repository.summaries[conv_id] = "User previously asked about groceries."

    provider = FakeOllamaProvider()
    app.dependency_overrides[get_model_provider] = lambda: provider

    client.post("/api/v1/chat", json={"conversation_id": conv_id, "message": "new question"})

    assert provider.last_request is not None
    sent = provider.last_request.messages
    assert sent[0] == {
        "role": "system",
        "content": "Earlier conversation summary: User previously asked about groceries.",
    }
    # 12 most recent messages (of the 21 now stored) plus the summary message.
    assert len(sent) == 13


async def test_conversation_summarized_after_twenty_messages(client, repository):
    conv_id = "conv-long"
    repository.conversations[conv_id] = ConversationRecord(
        id=conv_id,
        project_id=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        preview=None,
    )
    repository.messages[conv_id] = [
        MessageRecord(
            id=f"old-{i}", role="user", content=f"old {i}", created_at="2026-01-01T00:00:00"
        )
        for i in range(19)
    ]

    response = client.post("/api/v1/chat", json={"conversation_id": conv_id, "message": "one more"})

    assert response.status_code == 200
    assert repository.summaries.get(conv_id) == "요약된 대화 내용"


async def test_summary_generation_failure_does_not_break_chat_turn(client, repository):
    conv_id = "conv-long-failing-summary"
    repository.conversations[conv_id] = ConversationRecord(
        id=conv_id,
        project_id=None,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        preview=None,
    )
    repository.messages[conv_id] = [
        MessageRecord(
            id=f"old-{i}", role="user", content=f"old {i}", created_at="2026-01-01T00:00:00"
        )
        for i in range(19)
    ]

    class SummaryFailingProvider(FakeOllamaProvider):
        async def generate(self, request):
            raise ModelProviderError("Ollama unavailable")

    app.dependency_overrides[get_model_provider] = lambda: SummaryFailingProvider()

    response = client.post("/api/v1/chat", json={"conversation_id": conv_id, "message": "one more"})

    assert response.status_code == 200
    done = _done_event(response.text)
    assert done["provider"] == "ollama"
    assert conv_id not in repository.summaries
    assert repository.audit[-1]["success"] is True
