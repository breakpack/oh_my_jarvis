"""Async REST client for the Assistant API, plus the SSE chat-stream bridge.

Mirrors apps/cli's ApiError/_request_json pattern (async httpx instead of
sync) so every command-group module in this bot can call the exact same
backend endpoints the Web UI and `pai` CLI already use.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


class ApiError(RuntimeError):
    """Raised when a REST call to the API backend fails."""


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def extract_error_message(response: httpx.Response, body: bytes | None = None) -> str:
    raw = body if body is not None else response.content
    try:
        parsed = json.loads(raw) if raw else None
    except (ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        return str(parsed.get("error") or parsed.get("detail") or parsed)
    if parsed is not None:
        return str(parsed)
    text = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
    return text or f"HTTP {response.status_code}"


async def request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise ApiError(extract_error_message(response))
    if not response.content:
        return None
    return response.json()


async def stream_chat(
    client: httpx.AsyncClient,
    base_url: str,
    conversation_id: str | None,
    message: str,
    project_id: str | None,
    on_delta: Callable[[str], Awaitable[None]],
) -> dict[str, Any]:
    """POST /api/v1/chat, calling `on_delta` for each token as it arrives.
    Returns the "done" event payload (conversation_id, message_id, model,
    provider, evidence) or raises ApiError with the "error" event message."""
    payload: dict[str, Any] = {"conversation_id": conversation_id, "message": message}
    if project_id is not None:
        payload["project_id"] = project_id

    url = api_url(base_url, "/api/v1/chat")
    done_payload: dict[str, Any] = {}
    buffer = ""
    event_type = "message"
    data_lines: list[str] = []

    def flush() -> tuple[str, dict[str, Any]] | None:
        nonlocal event_type, data_lines
        if not data_lines:
            return None
        payload_text = "\n".join(data_lines)
        try:
            data = json.loads(payload_text)
        except json.JSONDecodeError:
            data = {"raw": payload_text}
        result = (event_type, data)
        event_type = "message"
        data_lines = []
        return result

    async with client.stream("POST", url, json=payload, timeout=120.0) as response:
        if response.status_code >= 400:
            body = await response.aread()
            raise ApiError(extract_error_message(response, body))
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if line == "":
                    flushed = flush()
                    if flushed is None:
                        continue
                    kind, data = flushed
                    if kind == "token":
                        await on_delta(data.get("delta", ""))
                    elif kind == "done":
                        done_payload = data
                    elif kind == "error":
                        raise ApiError(data.get("error", "unknown error"))
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
    return done_payload
