"""Workspace commands (mirrors `pai workspace`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.handlers_core import _http_client, _settings

WORKSPACES_ENDPOINT = "/api/v1/workspaces"

_FAILED = object()


async def _call(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    method: str,
    path: str,
    **kwargs: object,
) -> Any:
    """Returns the parsed response, or the `_FAILED` sentinel if an error
    was already reported to the user (distinct from a legitimate `None`
    response body, e.g. a DELETE with no content)."""
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        return await request_json(client, method, api_url(base_url, path), **kwargs)
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
    return _FAILED


@require_authorized
async def workspace_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /workspace_create <source>")
        return
    result = await _call(
        update, context, "POST", WORKSPACES_ENDPOINT, json={"source": context.args[0]}
    )
    if result is _FAILED:
        return
    await update.effective_message.reply_text(str((result or {}).get("id", "")))


@require_authorized
async def workspace_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "사용법: /workspace_run <workspace_id> <command...>"
        )
        return
    workspace_id, command = context.args[0], context.args[1:]
    result = await _call(
        update,
        context,
        "POST",
        f"{WORKSPACES_ENDPOINT}/{workspace_id}/run",
        json={"command": command},
    )
    if result is _FAILED:
        return
    result = result or {}
    exit_code = result.get("exit_code")
    lines = [f"exit_code={exit_code} duration_ms={result.get('duration_ms')}"]
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    if stdout:
        lines.append(f"stdout:\n{stdout}")
    if stderr:
        lines.append(f"stderr:\n{stderr}")
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def workspace_diff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /workspace_diff <workspace_id>")
        return
    result = await _call(update, context, "GET", f"{WORKSPACES_ENDPOINT}/{context.args[0]}/diff")
    if result is _FAILED:
        return
    diff = (result or {}).get("diff", "")
    await update.effective_message.reply_text(diff or "(변경 사항 없음)")


@require_authorized
async def workspace_commit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 2:
        await update.effective_message.reply_text(
            "사용법: /workspace_commit <workspace_id> <message...>"
        )
        return
    workspace_id = context.args[0]
    message = " ".join(context.args[1:])
    result = await _call(
        update,
        context,
        "POST",
        f"{WORKSPACES_ENDPOINT}/{workspace_id}/commit",
        json={"message": message},
    )
    if result is _FAILED:
        return
    result = result or {}
    if result.get("status") == "pending_approval":
        approval_id = result.get("approval_id", "")
        await update.effective_message.reply_text(
            f"승인 대기 중 (approval id: {approval_id})  "
            f"'/approval_approve {approval_id}'로 승인하세요"
        )
        return
    await update.effective_message.reply_text(json.dumps(result, indent=2, ensure_ascii=False))


@require_authorized
async def workspace_destroy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /workspace_destroy <workspace_id>")
        return
    workspace_id = context.args[0]
    result = await _call(update, context, "DELETE", f"{WORKSPACES_ENDPOINT}/{workspace_id}")
    if result is _FAILED:
        return
    await update.effective_message.reply_text(f"삭제됨: {workspace_id}")
