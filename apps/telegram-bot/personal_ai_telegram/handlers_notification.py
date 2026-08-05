"""Notification commands (mirrors `pai notification`) plus a background
poller that pushes new proactive notifications to the authorized chat."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.handlers_core import _http_client, _settings
from personal_ai_telegram.session_repository import SessionRepository

logger = logging.getLogger(__name__)

NOTIFICATIONS_ENDPOINT = "/api/v1/notifications"

# ponytail: hard floor so a misconfigured interval can't hammer the API.
POLL_INTERVAL_SECONDS = 60


def _format_priority(priority: str) -> str:
    return priority


def _notification_line(n: dict) -> str:
    return (
        f"{n.get('id', '')} | {n.get('source_type', '')} | "
        f"{_format_priority(str(n.get('priority', '')))} | {n.get('title', '')} | "
        f"{n.get('created_at', '')}"
    )


def _notification_keyboard(notification_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("확인", callback_data=f"notif:seen:{notification_id}"),
                InlineKeyboardButton("닫기", callback_data=f"notif:dismiss:{notification_id}"),
            ]
        ]
    )


@require_authorized
async def notification_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = context.args[0] if context.args else None
    params: dict[str, str] = {}
    if status is not None:
        params["status"] = status
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        notifications = await request_json(
            client, "GET", api_url(base_url, NOTIFICATIONS_ENDPOINT), params=params
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    notifications = notifications or []
    if not notifications:
        await update.effective_message.reply_text("(알림 없음)")
        return
    await update.effective_message.reply_text(
        "\n".join(_notification_line(n) for n in notifications)
    )


async def _resolve_notification(
    client: httpx.AsyncClient, base_url: str, notification_id: str, action: str
) -> str:
    path = f"{NOTIFICATIONS_ENDPOINT}/{notification_id}/{action}"
    try:
        await request_json(client, "POST", api_url(base_url, path))
    except ApiError as e:
        return f"오류: {e}"
    except httpx.HTTPError as e:
        return f"연결 실패: {e}"
    verb = "확인됨" if action == "seen" else "닫힘"
    return f"{verb}: {notification_id}"


@require_authorized
async def notification_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /notification_seen <notification_id>")
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_notification(client, base_url, context.args[0], "seen")
    await update.effective_message.reply_text(text)


@require_authorized
async def notification_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /notification_dismiss <notification_id>")
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_notification(client, base_url, context.args[0], "dismiss")
    await update.effective_message.reply_text(text)


@require_authorized
async def notification_checknow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        notifications = await request_json(
            client, "POST", api_url(base_url, f"{NOTIFICATIONS_ENDPOINT}/check-now")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    notifications = notifications or []
    await update.effective_message.reply_text(f"{len(notifications)}건의 새 알림")
    if notifications:
        await update.effective_message.reply_text(
            "\n".join(_notification_line(n) for n in notifications)
        )


@require_authorized
async def notification_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        _, action, notification_id = query.data.split(":", 2)
    except ValueError:
        return
    if action not in {"seen", "dismiss"}:
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_notification(client, base_url, notification_id, action)
    await query.edit_message_text(text)


async def _poll_once(
    application: Application, client: httpx.AsyncClient, settings: Settings, repo: SessionRepository
) -> None:
    chat_id = str(settings.telegram_allowed_user_id)
    session = await repo.get_or_create(chat_id)
    try:
        notifications = await request_json(
            client, "GET", api_url(settings.api_base_url, NOTIFICATIONS_ENDPOINT)
        )
    except (ApiError, httpx.HTTPError):
        logger.warning("notification poll failed", exc_info=True)
        return

    now = datetime.now(UTC)
    watermark = session.last_notification_check_at
    for n in notifications or []:
        created_at = n.get("created_at")
        if watermark is not None and created_at is not None:
            try:
                created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            except ValueError:
                created = None
            if created is not None and created <= watermark.replace(tzinfo=created.tzinfo):
                continue
        await application.bot.send_message(
            chat_id=chat_id,
            text=_notification_line(n),
            reply_markup=_notification_keyboard(str(n.get("id", ""))),
        )
    await repo.advance_notification_watermark(chat_id, now.replace(tzinfo=None))


async def notification_poll_loop(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    client: httpx.AsyncClient = application.bot_data["http_client"]
    repo: SessionRepository = application.bot_data["session_repository"]
    while True:
        try:
            await _poll_once(application, client, settings, repo)
        except Exception:  # noqa: BLE001 - the poll loop must never die
            logger.exception("notification poll iteration failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
