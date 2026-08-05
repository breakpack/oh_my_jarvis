"""Memory handlers: /memory_search, /memory_list, /memory_forget (mirrors
`pai memory search|list|forget`), scoped to the chat's active project if set."""

from __future__ import annotations

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import SessionRepository

MEMORIES_ENDPOINT = "/api/v1/memories"
MEMORIES_SEARCH_ENDPOINT = "/api/v1/memories/search"


def _repo(context: ContextTypes.DEFAULT_TYPE) -> SessionRepository:
    return context.bot_data["session_repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


def _truncate(text_value: str, limit: int = 80) -> str:
    return text_value if len(text_value) <= limit else text_value[: limit - 3] + "..."


def _format_memories(memories: list[dict]) -> str:
    if not memories:
        return "메모리가 없습니다."
    lines = ["Memories:"]
    for memory in memories:
        lines.append(
            f"{memory.get('id', '')} | {_truncate(str(memory.get('content', '')))} | "
            f"{memory.get('source', '')} | {memory.get('confidence', '')} | "
            f"{memory.get('valid_until', '')}"
        )
    return "\n".join(lines)


@require_authorized
async def memory_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /memory_search <query>")
        return
    query = " ".join(args)

    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    settings = _settings(context)
    client = _http_client(context)

    payload: dict[str, object] = {"query": query}
    if session.project_id is not None:
        payload["project_id"] = session.project_id
    try:
        memories = await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, MEMORIES_SEARCH_ENDPOINT),
            json=payload,
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    await update.effective_message.reply_text(_format_memories(memories or []))


@require_authorized
async def memory_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    settings = _settings(context)
    client = _http_client(context)

    params: dict[str, object] = {}
    if session.project_id is not None:
        params["project_id"] = session.project_id
    try:
        memories = await request_json(
            client, "GET", api_url(settings.api_base_url, MEMORIES_ENDPOINT), params=params
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    await update.effective_message.reply_text(_format_memories(memories or []))


@require_authorized
async def memory_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /memory_forget <memory_id>")
        return
    memory_id = args[0]

    settings = _settings(context)
    client = _http_client(context)
    try:
        await request_json(
            client, "DELETE", api_url(settings.api_base_url, f"{MEMORIES_ENDPOINT}/{memory_id}")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    await update.effective_message.reply_text(f"삭제됨: {memory_id}")
