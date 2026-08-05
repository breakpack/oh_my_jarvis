"""Gmail search tool — read-only (SPEC.md §7, §20.3).

Authenticates with a long-lived OAuth refresh token exchanged for a
short-lived access token per call (no google-api-python-client dependency;
httpx is already used everywhere else in this codebase for REST calls).
"""

from __future__ import annotations

import os

import httpx

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_TIMEOUT_SECONDS = 15
_MAX_RESULTS = 50
_DEFAULT_RESULTS = 10


def _credentials() -> tuple[str, str, str] | None:
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return None
    return client_id, client_secret, refresh_token


async def _get_access_token(
    client: httpx.AsyncClient, client_id: str, client_secret: str, refresh_token: str
) -> str:
    response = await client.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


class GmailSearchTool:
    name = "gmail.search_messages"
    description = (
        "목적: Gmail 받은편지함을 검색어(Gmail 검색 문법)로 조회해 제목/발신자/날짜/"
        "미리보기를 반환한다. "
        "언제 사용: 사용자가 '안 읽은 메일 있어?', '누구한테 온 메일 찾아줘' 등 메일함 "
        "조회를 요청할 때 사용한다. "
        "언제 사용하면 안 되는지: 메일을 발송/삭제/라벨 변경하는 용도로는 사용할 수 "
        "없다 (본 Tool은 읽기 전용 gmail.readonly 스코프만 사용한다). "
        "입력 의미: query는 Gmail 검색 쿼리 문법(예: 'from:example.com is:unread', "
        "필수), max_results는 반환할 최대 메일 개수(기본 10, 최대 50). "
        "외부 영향: 없음 — Gmail API에 읽기 요청만 보내며 메일 상태를 변경하지 않는다. "
        "반환값: data.messages에 각 메일의 id/subject/from/date/snippet이 담긴 리스트. "
        "오류 조건: GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET/GMAIL_REFRESH_TOKEN이 설정되지 "
        "않은 경우, OAuth 토큰 갱신이 실패한 경우(리프레시 토큰 만료/취소 포함), "
        "Gmail API가 오류를 반환한 경우, 요청이 15초 안에 끝나지 않는 경우 — 이 모든 "
        "경우 success=False와 error 메시지로 반환하며 예외를 던지지 않는다. "
        "승인 필요 여부: risk_level=read이므로 SPEC §12.1에 따라 자동 실행 가능 — "
        "승인 불필요."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail 검색 쿼리 (예: 'from:example.com is:unread')",
            },
            "max_results": {
                "type": "integer",
                "default": _DEFAULT_RESULTS,
                "minimum": 1,
                "maximum": _MAX_RESULTS,
                "description": "반환할 최대 메일 개수",
            },
        },
        "required": ["query"],
    }
    risk_level = "read"
    required_scopes = {"gmail.readonly"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        query = arguments.get("query", "")
        preview = f"Gmail에서 '{query}' 검색 예정"
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        creds = _credentials()
        if creds is None:
            return ToolResult(
                success=False,
                error=(
                    "Gmail 인증 정보가 설정되지 않았습니다. GMAIL_CLIENT_ID / "
                    "GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN을 .env에 설정하세요."
                ),
            )
        query = arguments.get("query")
        if not query:
            return ToolResult(success=False, error="query is required")
        try:
            max_results = int(arguments.get("max_results", _DEFAULT_RESULTS))
        except (TypeError, ValueError):
            return ToolResult(success=False, error="max_results must be an integer")
        if max_results <= 0:
            return ToolResult(success=False, error="max_results must be positive")
        max_results = min(max_results, _MAX_RESULTS)

        client_id, client_secret, refresh_token = creds
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                access_token = await _get_access_token(
                    client, client_id, client_secret, refresh_token
                )
                headers = {"Authorization": f"Bearer {access_token}"}
                list_response = await client.get(
                    f"{_API_BASE}/messages",
                    params={"q": query, "maxResults": max_results},
                    headers=headers,
                )
                list_response.raise_for_status()
                message_ids = [m["id"] for m in list_response.json().get("messages", [])]

                messages = []
                for message_id in message_ids:
                    detail_response = await client.get(
                        f"{_API_BASE}/messages/{message_id}",
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["Subject", "From", "Date"],
                        },
                        headers=headers,
                    )
                    detail_response.raise_for_status()
                    detail = detail_response.json()
                    header_map = {
                        h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])
                    }
                    messages.append(
                        {
                            "id": message_id,
                            "subject": header_map.get("Subject", ""),
                            "from": header_map.get("From", ""),
                            "date": header_map.get("Date", ""),
                            "snippet": detail.get("snippet", ""),
                        }
                    )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                error=(
                    f"Gmail API returned an error ({exc.response.status_code}): "
                    f"{exc.response.text[:300]}"
                ),
            )
        except httpx.HTTPError as exc:
            return ToolResult(success=False, error=f"failed to reach Gmail: {exc}")

        evidence = [
            {
                "source_type": "gmail_message",
                "source_id": m["id"],
                "title": m["subject"],
                "content": m["snippet"],
                "metadata": {"from": m["from"], "date": m["date"]},
            }
            for m in messages
        ]
        return ToolResult(success=True, data={"messages": messages}, evidence=evidence)

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        return result


default_tool_registry.register(GmailSearchTool())
