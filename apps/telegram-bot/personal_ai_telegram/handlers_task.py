"""Task commands (mirrors `pai task`)."""

from __future__ import annotations

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.handlers_core import _http_client, _repo, _settings

TASKS_ENDPOINT = "/api/v1/tasks"


@require_authorized
async def task_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    status = context.args[0] if context.args else None
    params: dict[str, str] = {}
    if session.project_id is not None:
        params["project_id"] = session.project_id
    if status is not None:
        params["status"] = status
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        tasks = await request_json(client, "GET", api_url(base_url, TASKS_ENDPOINT), params=params)
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    tasks = tasks or []
    if not tasks:
        await update.effective_message.reply_text("(작업 없음)")
        return
    lines = [
        f"{t.get('id', '')} | {t.get('title', '')} | {t.get('status', '')} | "
        f"due={t.get('due_at', '')}"
        for t in tasks
    ]
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def task_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /task_create <title> [description...]")
        return
    title = context.args[0]
    description = " ".join(context.args[1:]) if len(context.args) > 1 else None
    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    payload: dict[str, str] = {"title": title}
    if description is not None:
        payload["description"] = description
    if session.project_id is not None:
        payload["project_id"] = session.project_id
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        task = await request_json(client, "POST", api_url(base_url, TASKS_ENDPOINT), json=payload)
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    task = task or {}
    await update.effective_message.reply_text(f"생성됨: {task.get('id', '')}")


@require_authorized
async def task_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text("사용법: /task_update <task_id> <status>")
        return
    task_id, status = context.args[0], context.args[1]
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        task = await request_json(
            client,
            "PATCH",
            api_url(base_url, f"{TASKS_ENDPOINT}/{task_id}"),
            json={"status": status},
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    task = task or {}
    await update.effective_message.reply_text(
        f"수정됨: {task.get('id', task_id)} -> {task.get('status', status)}"
    )
