"""Chat API (SPEC.md §15 Chat, §2.1 Conversation): SSE-streamed replies backed
by the local Ollama provider, with conversation/message persistence and a
non-sensitive audit trail (SPEC.md §20.4).
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
    get_chat_repository,
)
from personal_ai_api.config import settings

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    local_only: bool = False


class ConversationOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    preview: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


def get_model_provider() -> ModelProvider:
    return OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_local_fast_model)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def post_chat(
    payload: ChatRequest,
    repository: ChatRepository = Depends(get_chat_repository),
    provider: ModelProvider = Depends(get_model_provider),
) -> StreamingResponse:
    user_id = await repository.get_or_create_default_user()

    try:
        conversation_id = await repository.get_or_create_conversation(
            payload.conversation_id, user_id
        )
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    await repository.add_message(conversation_id, "user", payload.message)
    history = await repository.list_messages(conversation_id)
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

        await repository.record_audit(
            user_id,
            "chat",
            {
                "conversation_id": conversation_id,
                "model": provider.model,
                "provider": provider.provider_name,
                "success": success,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "user_message_chars": len(payload.message),
                "assistant_message_chars": assistant_chars,
                "error": error_message,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations(
    repository: ChatRepository = Depends(get_chat_repository),
) -> list[ConversationOut]:
    user_id = await repository.get_or_create_default_user()
    conversations = await repository.list_conversations(user_id)
    return [ConversationOut(**vars(c)) for c in conversations]


@router.get("/conversations/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    repository: ChatRepository = Depends(get_chat_repository),
) -> list[MessageOut]:
    user_id = await repository.get_or_create_default_user()
    try:
        await repository.get_conversation(conversation_id, user_id)
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    messages = await repository.list_messages(conversation_id)
    return [MessageOut(**vars(m)) for m in messages]
