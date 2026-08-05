"""Knowledge handlers: /knowledge_search (mirrors `pai knowledge search`) and
a Document-attachment handler that ingests uploaded files (mirrors
`pai knowledge ingest`), both scoped to the chat's active project if set."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import SessionRepository

logger = logging.getLogger(__name__)

KNOWLEDGE_SEARCH_ENDPOINT = "/api/v1/knowledge/search"
DOCUMENTS_ENDPOINT = "/api/v1/documents"


def _repo(context: ContextTypes.DEFAULT_TYPE) -> SessionRepository:
    return context.bot_data["session_repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


def _truncate(text_value: str, limit: int = 80) -> str:
    return text_value if len(text_value) <= limit else text_value[: limit - 3] + "..."


@require_authorized
async def knowledge_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /knowledge_search <query>")
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
        results = await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, KNOWLEDGE_SEARCH_ENDPOINT),
            json=payload,
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    results = results or []
    if not results:
        await update.effective_message.reply_text("검색 결과가 없습니다.")
        return
    lines = ["Knowledge:"]
    for item in results:
        lines.append(
            f"{item.get('document_title', '')} | {item.get('page', '')} | "
            f"{item.get('score', '')} | {_truncate(str(item.get('content', '')))}"
        )
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def knowledge_ingest_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    document = message.document
    if document is None:
        return

    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    settings = _settings(context)
    client = _http_client(context)
    title = (message.caption or "").strip() or None
    file_name = document.file_name or "document"

    with tempfile.TemporaryDirectory() as tmp_dir:
        local_path = Path(tmp_dir) / file_name
        try:
            telegram_file = await context.bot.get_file(document.file_id)
            await telegram_file.download_to_drive(local_path)
        except Exception as e:  # noqa: BLE001 - any download failure must not crash the handler
            await message.reply_text(f"다운로드 실패: {e}")
            return

        data: dict[str, object] = {}
        if session.project_id is not None:
            data["project_id"] = session.project_id
        if title is not None:
            data["title"] = title

        try:
            with local_path.open("rb") as f:
                files = {"file": (file_name, f)}
                doc = await request_json(
                    client,
                    "POST",
                    api_url(settings.api_base_url, DOCUMENTS_ENDPOINT),
                    data=data,
                    files=files,
                )
        except ApiError as e:
            await message.reply_text(f"오류: {e}")
            return
        except httpx.HTTPError as e:
            await message.reply_text(f"연결 실패: {e}")
            return

    doc = doc or {}
    await message.reply_text(
        f"업로드됨: {doc.get('id', '')} ({doc.get('chunk_count', '?')} chunks)"
    )
