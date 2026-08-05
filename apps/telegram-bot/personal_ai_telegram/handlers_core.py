"""Core handlers: /start, /help, /doctor, /newconv, /model, and the
plain-text chat bridge (mirrors `pai ask` / `pai chat`, streamed via
Telegram message edits)."""

from __future__ import annotations

import asyncio
import logging

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json, stream_chat
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import SessionRepository

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Personal AI OS Telegram bot\n\n"
    "그냥 메시지를 보내면 채팅 응답을 받습니다.\n\n"
    "/doctor - 백엔드 상태 확인\n"
    "/newconv - 새 대화 시작\n"
    "/model - 현재 모델 확인, /model <name> - 모델 전환, /model_list - 사용 가능한 모델 목록\n"
    "/project_list, /project_create\n"
    "/memory_search, /memory_list, /memory_forget\n"
    "/knowledge_search, (파일 첨부로 업로드)\n"
    "/skill_list, /skill_inspect, /skill_enable, /skill_disable, /skill_run,\n"
    "/skill_audit, /skill_install, /skill_update, /skill_versions,\n"
    "/skill_rollback, /skill_remove\n"
    "/approval_list, /approval_approve, /approval_reject\n"
    "/task_list, /task_create, /task_update\n"
    "/workspace_create, /workspace_run, /workspace_diff, /workspace_commit,\n"
    "/workspace_destroy\n"
    "/workflow_run, /workflow_resume\n"
    "/notification_list, /notification_seen, /notification_dismiss,\n"
    "/notification_checknow\n"
)


def _repo(context: ContextTypes.DEFAULT_TYPE) -> SessionRepository:
    return context.bot_data["session_repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


@require_authorized
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    await _repo(context).get_or_create(chat_id)
    await update.effective_message.reply_text(HELP_TEXT)


@require_authorized
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


@require_authorized
async def newconv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    await _repo(context).set_conversation(chat_id, None)
    await update.effective_message.reply_text("새 대화를 시작합니다.")


@require_authorized
async def model_show_or_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    repo = _repo(context)
    args = context.args or []
    if not args:
        session = await repo.get_or_create(chat_id)
        await update.effective_message.reply_text(f"현재 모델: {session.model or '(서버 기본값)'}")
        return
    model = args[0]
    await repo.set_model(chat_id, model)
    await update.effective_message.reply_text(f"모델 전환: {model}")


@require_authorized
async def model_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    client = _http_client(context)
    try:
        models = await request_json(client, "GET", api_url(settings.api_base_url, "/api/v1/models"))
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    models = models or []
    if not models:
        await update.effective_message.reply_text("사용 가능한 모델이 없습니다.")
        return
    lines = [f"{m.get('name', '')}" for m in models]
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    client = _http_client(context)
    try:
        response = await client.get(f"{settings.api_base_url.rstrip('/')}/health", timeout=5.0)
        response.raise_for_status()
        await update.effective_message.reply_text(f"OK: {response.json()}")
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"FAIL: {e}")


_EDIT_INTERVAL_SECONDS = 0.7


@require_authorized
async def chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text or ""
    if not text.strip():
        return

    chat_id = str(update.effective_chat.id)
    repo = _repo(context)
    session = await repo.get_or_create(chat_id)
    client = _http_client(context)
    settings = _settings(context)

    placeholder = await message.reply_text("...")
    buffer: list[str] = []
    last_edit = asyncio.get_event_loop().time()

    async def on_delta(delta: str) -> None:
        nonlocal last_edit
        buffer.append(delta)
        now = asyncio.get_event_loop().time()
        if now - last_edit < _EDIT_INTERVAL_SECONDS:
            return
        last_edit = now
        try:
            await placeholder.edit_text("".join(buffer) or "...")
        except Exception:  # noqa: BLE001 - a mid-stream edit failure must not abort the stream
            logger.debug("message edit failed mid-stream", exc_info=True)

    try:
        done = await stream_chat(
            client,
            settings.api_base_url,
            session.conversation_id,
            text,
            session.project_id,
            on_delta,
            session.model,
        )
    except ApiError as e:
        await placeholder.edit_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await placeholder.edit_text(f"연결 실패: {e}")
        return

    full_text = "".join(buffer) or "(빈 응답)"
    try:
        await placeholder.edit_text(full_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:  # noqa: BLE001 - markdown parse can fail on model output; fall back to plain
        await placeholder.edit_text(full_text)

    new_conversation_id = done.get("conversation_id")
    if new_conversation_id and new_conversation_id != session.conversation_id:
        await repo.set_conversation(chat_id, new_conversation_id)
