"""Workflow handlers: /workflow_run, /workflow_resume (mirrors `pai workflow
run|resume`, the durable/restart-safe counterpart of /skill_run)."""

from __future__ import annotations

import json

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.handlers_skill import render_skill_result_lines

WORKFLOWS_ENDPOINT = "/api/v1/workflows"


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


async def _render_workflow_response(update: Update, response: dict) -> None:
    if response.get("status") == "pending_approval":
        thread_id = response.get("thread_id", "")
        await update.effective_message.reply_text(
            f"승인 대기 중 (thread: {thread_id})\n"
            f"'/workflow_resume {thread_id} approve' (또는 reject)로 진행하세요"
        )
        return
    result = response.get("result") or {}
    await update.effective_message.reply_text("\n".join(render_skill_result_lines(result)))


@require_authorized
async def workflow_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("사용법: /workflow_run <skill_name> <json>")
        return
    skill_name = args[0]
    # Reassembling the JSON by joining whitespace-split args only round-trips
    # for compact JSON with no internal spaces (e.g. {"key":"value"}).
    input_text = " ".join(args[1:])
    try:
        arguments = json.loads(input_text)
    except json.JSONDecodeError as e:
        await update.effective_message.reply_text(f"오류: JSON이 올바르지 않습니다: {e}")
        return
    if not isinstance(arguments, dict):
        await update.effective_message.reply_text("오류: JSON은 객체여야 합니다")
        return

    settings = _settings(context)
    client = _http_client(context)
    try:
        response = await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, f"{WORKFLOWS_ENDPOINT}/skills/{skill_name}/run"),
            json={"arguments": arguments},
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    await _render_workflow_response(update, response or {})


@require_authorized
async def workflow_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "사용법: /workflow_resume <thread_id> <approve|reject>"
        )
        return
    thread_id, decision = args[0], args[1]
    if decision not in {"approve", "reject"}:
        await update.effective_message.reply_text(
            "오류: decision은 'approve' 또는 'reject'여야 합니다"
        )
        return

    settings = _settings(context)
    client = _http_client(context)
    try:
        response = await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, f"{WORKFLOWS_ENDPOINT}/{thread_id}/resume"),
            json={"decision": decision},
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    await _render_workflow_response(update, response or {})
