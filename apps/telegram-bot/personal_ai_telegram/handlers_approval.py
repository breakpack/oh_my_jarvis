"""Approval commands, plus inline approve/reject buttons (mirrors `pai approval`)."""

from __future__ import annotations

import json

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.handlers_core import _http_client, _settings

APPROVALS_ENDPOINT = "/api/v1/approvals"


def _approval_keyboard(approval_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("승인", callback_data=f"approval:approve:{approval_id}"),
                InlineKeyboardButton("거부", callback_data=f"approval:reject:{approval_id}"),
            ]
        ]
    )


def _render_result(result: object) -> str:
    if isinstance(result, dict) and "success" in result:
        lines = []
        success = bool(result.get("success"))
        lines.append(f"{'성공' if success else '실패'}: {result.get('summary', '')}")
        error = result.get("error")
        if error:
            lines.append(f"오류: {error}")
        for label, key in (("evidence", "evidence"), ("artifacts", "artifacts")):
            items = result.get(key) or []
            for item in items:
                lines.append(f"{label}: {item}")
        rollback_token = result.get("rollback_token")
        if rollback_token:
            lines.append(f"rollback token: {rollback_token}")
        return "\n".join(lines)
    if isinstance(result, dict):
        return json.dumps(result, indent=2, ensure_ascii=False)
    if result is not None:
        return str(result)
    return ""


@require_authorized
async def approval_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = context.args[0] if context.args else None
    params: dict[str, str] = {}
    if status is not None:
        params["status"] = status
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    try:
        approvals = await request_json(
            client, "GET", api_url(base_url, APPROVALS_ENDPOINT), params=params
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    approvals = approvals or []
    if not approvals:
        await update.effective_message.reply_text("(대기 중인 승인 없음)")
        return
    for approval in approvals:
        approval_id = str(approval.get("id", ""))
        lines = [
            f"{approval_id} | {approval.get('action', '')} | {approval.get('target', '')}",
            f"risk_level={approval.get('risk_level', '')} status={approval.get('status', '')} "
            f"expires_at={approval.get('expires_at', '')}",
        ]
        preview = approval.get("preview")
        if preview:
            lines.append(f"preview: {preview}")
        keyboard = _approval_keyboard(approval_id) if approval.get("status") == "pending" else None
        await update.effective_message.reply_text("\n".join(lines), reply_markup=keyboard)


async def _resolve_approval(
    client: httpx.AsyncClient, base_url: str, approval_id: str, decision: str
) -> str:
    path = f"{APPROVALS_ENDPOINT}/{approval_id}/{decision}"
    try:
        result = await request_json(client, "POST", api_url(base_url, path))
    except ApiError as e:
        return f"오류: {e}"
    except httpx.HTTPError as e:
        return f"연결 실패: {e}"
    verb = "승인됨" if decision == "approve" else "거부됨"
    rendered = _render_result(result)
    return f"{verb}: {approval_id}" + (f"\n{rendered}" if rendered else "")


@require_authorized
async def approval_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /approval_approve <approval_id>")
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_approval(client, base_url, context.args[0], "approve")
    await update.effective_message.reply_text(text)


@require_authorized
async def approval_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("사용법: /approval_reject <approval_id>")
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_approval(client, base_url, context.args[0], "reject")
    await update.effective_message.reply_text(text)


@require_authorized
async def approval_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback query handler for the inline 승인/거부 buttons."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    try:
        _, decision, approval_id = query.data.split(":", 2)
    except ValueError:
        return
    if decision not in {"approve", "reject"}:
        return
    client = _http_client(context)
    base_url = _settings(context).api_base_url
    text = await _resolve_approval(client, base_url, approval_id, decision)
    await query.edit_message_text(text)
