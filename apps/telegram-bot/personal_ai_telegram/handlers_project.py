"""Project handlers: /project_list, /project_create, /project_use (mirrors
`pai project list|create` plus a sticky per-chat `--project` via session state)."""

from __future__ import annotations

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import SessionRepository

PROJECTS_ENDPOINT = "/api/v1/projects"


def _repo(context: ContextTypes.DEFAULT_TYPE) -> SessionRepository:
    return context.bot_data["session_repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


@require_authorized
async def project_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    client = _http_client(context)
    try:
        projects = await request_json(
            client, "GET", api_url(settings.api_base_url, PROJECTS_ENDPOINT)
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    projects = projects or []
    if not projects:
        await update.effective_message.reply_text("프로젝트가 없습니다.")
        return
    lines = ["Projects:"]
    for project in projects:
        lines.append(
            f"{project.get('id', '')} | {project.get('name', '')} | "
            f"{project.get('status', '')} | {project.get('created_at', '')}"
        )
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def project_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /project_create <name> [description]")
        return
    name = args[0]
    description = " ".join(args[1:]) or None

    settings = _settings(context)
    client = _http_client(context)
    payload: dict[str, object] = {"name": name}
    if description is not None:
        payload["description"] = description
    try:
        project = await request_json(
            client, "POST", api_url(settings.api_base_url, PROJECTS_ENDPOINT), json=payload
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    project = project or {}
    await update.effective_message.reply_text(f"생성됨: {project.get('id', '')}")


@require_authorized
async def project_use(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    args = context.args or []
    repo = _repo(context)
    if not args:
        await repo.set_project(chat_id, None)
        await update.effective_message.reply_text("활성 프로젝트를 해제했습니다.")
        return
    project_id = args[0]
    await repo.set_project(chat_id, project_id)
    await update.effective_message.reply_text(f"활성 프로젝트: {project_id}")
