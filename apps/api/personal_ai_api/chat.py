"""Chat API (SPEC.md §15 Chat, §2.1 Conversation): SSE-streamed replies backed
by the local Ollama provider, with conversation/message persistence, a
non-sensitive audit trail (SPEC.md §20.4), rolling summaries, and the
/remember, /forget, /no-memory chat commands (SPEC.md §8.3).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from personal_ai.models.providers import (
    DeepSeekProvider,
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
from personal_ai_api.knowledge_repository import (
    KnowledgeRepository,
    SearchResult,
    get_knowledge_repository,
)
from personal_ai_api.memory_repository import (
    MemoryRepository,
    get_memory_repository,
)
from personal_ai_api.summarizer import maybe_summarize_conversation

router = APIRouter(prefix="/api/v1", tags=["chat"])

RECENT_MESSAGES_WITH_SUMMARY = 12
COMMAND_NAMES = {"/remember": "remember", "/forget": "forget", "/no-memory": "no_memory"}
EVIDENCE_TOP_K = 5
EVIDENCE_SNIPPET_CHARS = 200


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str
    project_id: str | None = None
    local_only: bool = False
    model: str | None = None


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


class ModelOut(BaseModel):
    name: str
    size: int | None = None


def get_model_provider(payload: ChatRequest) -> ModelProvider:
    # payload.model lets a request pick any model `ollama list` (or, for a
    # "deepseek*" name, DeepSeek's cloud API) knows about, overriding the
    # OLLAMA_LOCAL_FAST_MODEL default for just this call.
    model = payload.model
    wants_deepseek = model is not None and model.startswith("deepseek")
    if wants_deepseek and payload.local_only:
        raise HTTPException(
            status_code=400,
            detail=f"model '{model}' requires cloud access but local_only=True was requested",
        )
    if wants_deepseek:
        if not settings.deepseek_api_key:
            raise HTTPException(status_code=400, detail="DEEPSEEK_API_KEY is not configured")
        assert model is not None  # narrowed by wants_deepseek above
        return DeepSeekProvider(
            api_key=settings.deepseek_api_key, model=model, base_url=settings.deepseek_base_url
        )
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=model or settings.ollama_local_fast_model,
        keep_alive=settings.ollama_keep_alive,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _evidence_system_message(results: list[SearchResult]) -> dict:
    lines = []
    for i, result in enumerate(results, start=1):
        location = f" (p.{result.page})" if result.page is not None else ""
        snippet = result.content[:EVIDENCE_SNIPPET_CHARS]
        lines.append(f"{i}) {result.document_title}{location}: {snippet}")
    return {
        "role": "system",
        "content": (
            "Relevant documents:\n"
            + "\n".join(lines)
            + "\n답변에 이 문서 내용을 반영하고, 근거로 사용한 경우 자연스럽게 언급해라."
        ),
    }


def _evidence_payload(results: list[SearchResult]) -> list[dict]:
    return [
        {
            "document_id": r.document_id,
            "document_title": r.document_title,
            "chunk_id": r.chunk_id,
            "page": r.page,
            "score": r.score,
        }
        for r in results
    ]


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
            "evidence": [],
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
    knowledge_repository: KnowledgeRepository = Depends(get_knowledge_repository),
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

    # SPEC §2.3/§8: ground the answer in the active project's documents when
    # there is one. No pre-check for "does this project have any documents" —
    # just try the search, and swallow empty results or failures (Ollama down,
    # no embeddings yet, ...) so evidence lookup never blocks the chat turn.
    evidence_results: list[SearchResult] = []
    if payload.project_id:
        try:
            evidence_results = await knowledge_repository.search(
                user_id, payload.message, project_id=payload.project_id, top_k=EVIDENCE_TOP_K
            )
        except Exception:
            evidence_results = []
    if evidence_results:
        provider_messages = [_evidence_system_message(evidence_results), *provider_messages]

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
                    "evidence": _evidence_payload(evidence_results),
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


@router.get("/models")
async def list_models() -> list[ModelOut]:
    models: list[ModelOut] = []

    ollama_url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(ollama_url)
            response.raise_for_status()
        models.extend(
            ModelOut(name=m["name"], size=m.get("size"))
            for m in response.json().get("models", [])
            if m.get("name")
        )
    except httpx.HTTPError:
        pass  # Ollama being unreachable shouldn't hide any configured cloud models

    if settings.deepseek_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{settings.deepseek_base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                )
                response.raise_for_status()
            models.extend(
                ModelOut(name=m["id"]) for m in response.json().get("data", []) if m.get("id")
            )
        except httpx.HTTPError:
            pass  # DeepSeek unreachable/misconfigured shouldn't hide the local model list

    return models


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
