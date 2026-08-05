"""Skill handlers: /skill_list, /skill_inspect, /skill_enable, /skill_disable,
/skill_run, /skill_audit, /skill_install, /skill_update, /skill_versions,
/skill_rollback, /skill_remove (mirrors `pai skill ...`)."""

from __future__ import annotations

import json

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from personal_ai_telegram.api_client import ApiError, api_url, extract_error_message, request_json
from personal_ai_telegram.auth import require_authorized
from personal_ai_telegram.config import Settings
from personal_ai_telegram.session_repository import SessionRepository

SKILLS_ENDPOINT = "/api/v1/skills"


def _repo(context: ContextTypes.DEFAULT_TYPE) -> SessionRepository:
    return context.bot_data["session_repository"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def _http_client(context: ContextTypes.DEFAULT_TYPE) -> httpx.AsyncClient:
    return context.bot_data["http_client"]


def render_skill_result_lines(result: dict) -> list[str]:
    """Plain-text equivalent of the CLI's render_skill_result (shared with
    handlers_workflow.py, since workflow responses embed the same SkillResult
    shape)."""
    success = bool(result.get("success"))
    lines = [f"{'SUCCESS' if success else 'FAILED'} {result.get('summary', '')}"]

    error = result.get("error")
    if error:
        lines.append(f"오류: {error}")

    for label, key in (("evidence", "evidence"), ("artifacts", "artifacts")):
        items = result.get(key) or []
        if items:
            lines.append(f"{label}:")
            for item in items:
                lines.append(f"  - {item}")

    rollback_token = result.get("rollback_token")
    if rollback_token:
        lines.append(f"rollback token: {rollback_token}")

    return lines


async def _install_skill(client: httpx.AsyncClient, base_url: str, source_path: str) -> dict:
    """POST /skills/install. A blocked install is a 422 with the same
    {"skill","audit"} shape as a 200/201 success, so unlike request_json this
    treats 422 as a normal (non-exception) response (mirrors the CLI's
    install_skill)."""
    response = await client.post(
        api_url(base_url, f"{SKILLS_ENDPOINT}/install"),
        json={"source_path": source_path},
    )
    if response.status_code not in (200, 201, 422):
        raise ApiError(extract_error_message(response))
    if not response.content:
        return {}
    return response.json()


def _render_install_result_lines(result: dict, verb: str) -> tuple[list[str], bool]:
    """Plain-text equivalent of the CLI's render_install_result."""
    audit = result.get("audit") or {}
    passed = bool(audit.get("passed"))
    skill = result.get("skill") or {}
    lines: list[str] = []

    if passed and skill:
        lines.append(f"{verb}됨: {skill.get('name', '')} v{skill.get('version', '')}")
        preview = audit.get("permissions_preview") or {}
        risk_level = preview.get("risk_level", skill.get("risk_level", ""))
        scopes = preview.get("scopes") or []
        lines.append(
            f"권한: risk_level={risk_level} scopes={', '.join(str(s) for s in scopes) or '(none)'}"
        )
        file_hash = audit.get("file_hash")
        if file_hash:
            lines.append(f"file_hash: {file_hash}")
    else:
        lines.append(f"설치가 거부됨 ({verb} 실패)")

    findings = audit.get("findings") or []
    for finding in findings:
        lines.append(
            f"- {finding.get('check', '')} [{finding.get('severity', '')}] "
            f"{finding.get('message', '')}"
        )

    return lines, passed


@require_authorized
async def skill_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else None
    settings = _settings(context)
    client = _http_client(context)
    params = {"query": query} if query is not None else {}
    try:
        result = await request_json(
            client, "GET", api_url(settings.api_base_url, SKILLS_ENDPOINT), params=params
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    result = result or {}
    skills = result.get("skills") or []
    lines = ["Skills:"] if skills else ["스킬이 없습니다."]
    for skill in skills:
        enabled = "yes" if skill.get("enabled") else "no"
        lines.append(
            f"{skill.get('name', '')} | {skill.get('display_name', '')} | "
            f"v{skill.get('version', '')} | risk={skill.get('risk_level', '')} | "
            f"enabled={enabled}"
        )
    invalid = result.get("invalid") or []
    if invalid:
        lines.append("invalid skills (failed to load):")
        for item in invalid:
            lines.append(f"  - {item.get('path', '')}: {item.get('error', '')}")
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_inspect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_inspect <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        detail = await request_json(
            client, "GET", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    detail = detail or {}
    display_name = detail.get("display_name") or detail.get("name", "")
    lines = [
        f"{display_name} ({detail.get('name', '')}) v{detail.get('version', '')}",
        f"risk_level={detail.get('risk_level', '')} "
        f"enabled={'yes' if detail.get('enabled') else 'no'}",
    ]
    tags = detail.get("tags") or []
    if tags:
        lines.append(f"tags: {', '.join(str(t) for t in tags)}")
    description = detail.get("description")
    if description:
        lines.append(description)
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_enable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_enable <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        await request_json(
            client, "POST", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/enable")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    await update.effective_message.reply_text(f"활성화됨: {name}")


@require_authorized
async def skill_disable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_disable <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        await request_json(
            client, "POST", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/disable")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    await update.effective_message.reply_text(f"비활성화됨: {name}")


@require_authorized
async def skill_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("사용법: /skill_run <name> <json>")
        return
    name = args[0]
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

    chat_id = str(update.effective_chat.id)
    session = await _repo(context).get_or_create(chat_id)
    settings = _settings(context)
    client = _http_client(context)
    payload: dict = {"arguments": arguments}
    if session.project_id is not None:
        payload["project_id"] = session.project_id
    try:
        result = await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/run"),
            json=payload,
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    result = result or {}
    if result.get("status") == "pending_approval":
        approval_id = result.get("approval_id", "")
        await update.effective_message.reply_text(
            f"승인 대기 중 (approval id: {approval_id})\n"
            f"'/approval_approve {approval_id}'로 승인하세요"
        )
        return
    await update.effective_message.reply_text("\n".join(render_skill_result_lines(result)))


@require_authorized
async def skill_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_audit <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        entries = await request_json(
            client, "GET", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/audit")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    entries = entries or []
    if not entries:
        await update.effective_message.reply_text("감사 로그가 없습니다.")
        return
    lines = ["Skill Audit Log:"]
    for entry in entries:
        result_value = entry.get("result", entry.get("status", ""))
        lines.append(
            f"{entry.get('id', '')} | {entry.get('action', '')} | {result_value} | "
            f"{entry.get('risk_level', '')} | {entry.get('created_at', '')}"
        )
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_install(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_install <source_path>")
        return
    source_path = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        result = await _install_skill(client, settings.api_base_url, source_path)
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    lines, _passed = _render_install_result_lines(result, "설치")
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("사용법: /skill_update <name> <source_path>")
        return
    name, source_path = args[0], args[1]
    settings = _settings(context)
    client = _http_client(context)
    try:
        result = await _install_skill(client, settings.api_base_url, source_path)
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    updated_name = (result.get("skill") or {}).get("name", name)
    lines, _passed = _render_install_result_lines(result, "업데이트")
    if updated_name != name:
        lines.insert(0, f"경고: 설치된 스킬 이름({updated_name})이 요청한 이름({name})과 다릅니다")
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_versions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_versions <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        versions = await request_json(
            client, "GET", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/versions")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return

    versions = versions or []
    if not versions:
        await update.effective_message.reply_text("설치된 버전이 없습니다.")
        return
    lines = ["Skill Versions:"]
    for version in versions:
        lines.append(f"{version.get('version', '')} | {version.get('created_at', '')}")
    await update.effective_message.reply_text("\n".join(lines))


@require_authorized
async def skill_rollback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text("사용법: /skill_rollback <name> <version>")
        return
    name, version = args[0], args[1]
    settings = _settings(context)
    client = _http_client(context)
    try:
        await request_json(
            client,
            "POST",
            api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/rollback"),
            json={"version": version},
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    await update.effective_message.reply_text(f"롤백됨: {name} -> {version}")


@require_authorized
async def skill_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("사용법: /skill_remove <name>")
        return
    name = args[0]
    settings = _settings(context)
    client = _http_client(context)
    try:
        await request_json(
            client, "DELETE", api_url(settings.api_base_url, f"{SKILLS_ENDPOINT}/{name}/store")
        )
    except ApiError as e:
        await update.effective_message.reply_text(f"오류: {e}")
        return
    except httpx.HTTPError as e:
        await update.effective_message.reply_text(f"연결 실패: {e}")
        return
    await update.effective_message.reply_text(f"제거됨: {name}")
