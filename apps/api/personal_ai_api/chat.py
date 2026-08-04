"""Chat API (SPEC.md §15 Chat, §2.1 Conversation): SSE-streamed replies backed
by the local Ollama provider, with conversation/message persistence, a
non-sensitive audit trail (SPEC.md §20.4), rolling summaries, and the
/remember, /forget, /no-memory chat commands (SPEC.md §8.3).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from personal_ai.models.providers import (
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    OllamaProvider,
)
from personal_ai_api.chat_repository import (
    ChatRepository,
    ConversationNotFound,
    ConversationRecord,
    get_chat_repository,
)
from personal_ai_api.config import settings
from personal_ai_api.memory_repository import (
    MemoryRepository,
    get_memory_repository,
)
from personal_ai_api.summarizer import maybe_summarize_conversation

router = APIRouter(prefix="/api/v1", tags=["chat"])

RECENT_MESSAGES_WITH_SUMMARY = 12
COMMAND_NAMES = {"/remember": "remember", "/forget": "forget", "/no-memory": "no_memory"}


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    project_id: str | None = None
    local_only: bool = False


class ConversationOut(BaseModel):
    id: str
    project_id: str | None = None
    created_at: str
    updated_at: str
    preview: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class ConversationDetailOut(BaseModel):
    id: str
    project_id: str | None = None
    summary: str | None = None
    messages: list[MessageOut]


def get_model_provider() -> ModelProvider:
    return OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_local_fast_model)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _parse_command(message: str) -> tuple[str | None, str]:
    """Split a leading /remember, /forget, or /no-memory prefix off `message`.

    Returns (command_name, remainder) — command_name is None for ordinary chat.
    """
    stripped = message.strip()
    for prefix, name in COMMAND_NAMES.items():
        if stripped == prefix:
            return name, ""
        if stripped.startswith(prefix + " "):
            return name, stripped[len(prefix) :].strip()
    return None, message


async def _run_command_turn(
    repository: ChatRepository,
    memory_repository: MemoryRepository,
    conversation: ConversationRecord,
    user_id: str,
    command: str,
    remainder: str,
    user_message_chars: int,
) -> AsyncIterator[str]:
    started = time.monotonic()

    if command == "remember":
        if not remainder:
            reply = "사용법: /remember <내용>"
        else:
            # SPEC §8.3 policy: confidence=1.0 is always above the 0.5 floor, so
            # an explicit /remember always persists.
            await memory_repository.create_memory(
                user_id=user_id,
                content=remainder,
                project_id=conversation.project_id,
                source="explicit_remember",
                confidence=1.0,
                valid_until=None,
            )
            reply = f"✓ Remembered: {remainder}"
    else:
        if not remainder:
            # Guard against an empty query, which would ILIKE-match (and delete)
            # every memory the user owns.
            reply = "사용법: /forget <검색어>"
        else:
            count = await memory_repository.delete_memories_by_content(
                user_id=user_id, project_id=conversation.project_id, query=remainder
            )
            if count:
                plural = "y" if count == 1 else "ies"
                reply = f"✓ Forgot {count} memor{plural} matching '{remainder}'."
            else:
                reply = "No matching memories found."

    yield _sse("token", {"delta": reply})
    assistant_message = await repository.add_message(conversation.id, "assistant", reply)
    yield _sse(
        "done",
        {
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "model": "system",
            "provider": "command",
        },
    )

    await repository.record_audit(
        user_id,
        "chat",
        {
            "conversation_id": conversation.id,
            "model": "system",
            "provider": "command",
            "success": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "user_message_chars": user_message_chars,
            "assistant_message_chars": len(reply),
            "error": None,
            "command": command,
        },
    )


@router.post("/chat")
async def post_chat(
    payload: ChatRequest,
    repository: ChatRepository = Depends(get_chat_repository),
    memory_repository: MemoryRepository = Depends(get_memory_repository),
    provider: ModelProvider = Depends(get_model_provider),
) -> StreamingResponse:
    user_id = await repository.get_or_create_default_user()

    try:
        conversation_id = await repository.get_or_create_conversation(
            payload.conversation_id, user_id, project_id=payload.project_id
        )
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    conversation = await repository.get_conversation(conversation_id, user_id)
    command, remainder = _parse_command(payload.message)

    # SPEC §8.3: /no-memory opts this turn out of automatic memory extraction.
    # There's no auto-extraction hook yet (Phase 2 only has explicit /remember),
    # so this is currently a no-op; wire `no_memory=True` into that hook's call
    # once it exists.
    stored_content = remainder if command == "no_memory" else payload.message
    await repository.add_message(conversation_id, "user", stored_content)

    if command in ("remember", "forget"):
        return StreamingResponse(
            _run_command_turn(
                repository,
                memory_repository,
                conversation,
                user_id,
                command,
                remainder,
                len(stored_content),
            ),
            media_type="text/event-stream",
        )

    history = await repository.list_messages(conversation_id)
    summary = await repository.get_conversation_summary(conversation_id)
    if summary:
        provider_messages = [
            {"role": "system", "content": f"Earlier conversation summary: {summary}"}
        ] + [
            {"role": m.role, "content": m.content} for m in history[-RECENT_MESSAGES_WITH_SUMMARY:]
        ]
    else:
        provider_messages = [{"role": m.role, "content": m.content} for m in history]

    async def event_stream() -> AsyncIterator[str]:
        started = time.monotonic()
        collected: list[str] = []
        error_message: str | None = None

        try:
            async for delta in provider.stream(
                ModelRequest(messages=provider_messages, local_only=payload.local_only)
            ):
                collected.append(delta)
                yield _sse("token", {"delta": delta})
        except ModelProviderError as exc:
            error_message = str(exc)
            yield _sse("error", {"error": error_message})
        except Exception:
            error_message = "Unexpected error while generating a response."
            yield _sse("error", {"error": error_message})

        success = error_message is None
        assistant_chars = 0

        if success:
            assistant_content = "".join(collected)
            assistant_chars = len(assistant_content)
            assistant_message = await repository.add_message(
                conversation_id, "assistant", assistant_content
            )
            yield _sse(
                "done",
                {
                    "conversation_id": conversation_id,
                    "message_id": assistant_message.id,
                    "model": provider.model,
                    "provider": provider.provider_name,
                },
            )
            await maybe_summarize_conversation(repository, provider, conversation_id)

        await repository.record_audit(
            user_id,
            "chat",
            {
                "conversation_id": conversation_id,
                "model": provider.model,
                "provider": provider.provider_name,
                "success": success,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "user_message_chars": len(stored_content),
                "assistant_message_chars": assistant_chars,
                "error": error_message,
                "command": command,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations(
    project_id: str | None = None,
    repository: ChatRepository = Depends(get_chat_repository),
) -> list[ConversationOut]:
    user_id = await repository.get_or_create_default_user()
    conversations = await repository.list_conversations(user_id, project_id=project_id)
    return [ConversationOut(**vars(c)) for c in conversations]


@router.get("/conversations/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    repository: ChatRepository = Depends(get_chat_repository),
) -> ConversationDetailOut:
    user_id = await repository.get_or_create_default_user()
    try:
        conversation = await repository.get_conversation(conversation_id, user_id)
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    messages = await repository.list_messages(conversation_id)
    summary = await repository.get_conversation_summary(conversation_id)
    return ConversationDetailOut(
        id=conversation.id,
        project_id=conversation.project_id,
        summary=summary,
        messages=[MessageOut(**vars(m)) for m in messages],
    )
