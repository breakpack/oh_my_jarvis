import httpx
import pytest
from personal_ai_cli.main import (
    ChatError,
    SSEEvent,
    _resolve_local_only,
    parse_sse_lines,
    stream_chat_response,
)


def sse_lines(*raw: str) -> list[str]:
    return list(raw)


def test_parse_sse_lines_parses_token_and_done_events() -> None:
    lines = sse_lines(
        "event: token",
        'data: {"delta": "Hel"}',
        "",
        "event: token",
        'data: {"delta": "lo"}',
        "",
        "event: done",
        'data: {"conversation_id": "c1", "message_id": "m1", '
        '"model": "gemma4:e2b", "provider": "ollama"}',
        "",
    )
    events = list(parse_sse_lines(lines))
    assert events == [
        SSEEvent("token", {"delta": "Hel"}),
        SSEEvent("token", {"delta": "lo"}),
        SSEEvent(
            "done",
            {
                "conversation_id": "c1",
                "message_id": "m1",
                "model": "gemma4:e2b",
                "provider": "ollama",
            },
        ),
    ]


def test_parse_sse_lines_handles_trailing_event_without_final_blank_line() -> None:
    lines = sse_lines("event: token", 'data: {"delta": "hi"}')
    events = list(parse_sse_lines(lines))
    assert events == [SSEEvent("token", {"delta": "hi"})]


def test_parse_sse_lines_ignores_comments_and_defaults_event_type() -> None:
    lines = sse_lines(":heartbeat", 'data: {"delta": "x"}', "")
    events = list(parse_sse_lines(lines))
    assert events == [SSEEvent("message", {"delta": "x"})]


def test_parse_sse_lines_falls_back_to_raw_on_bad_json() -> None:
    lines = sse_lines("event: token", "data: not-json", "")
    events = list(parse_sse_lines(lines))
    assert events == [SSEEvent("token", {"raw": "not-json"})]


def test_resolve_local_only() -> None:
    assert _resolve_local_only(local=True, cloud=False) is True
    assert _resolve_local_only(local=False, cloud=True) is False
    assert _resolve_local_only(local=False, cloud=False) is None


def _client_with_sse_body(body: bytes, status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code, content=body, headers={"content-type": "text/event-stream"}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_stream_chat_response_prints_tokens_and_returns_done_payload(capsys) -> None:
    body = (
        b'event: token\ndata: {"delta": "Hel"}\n\n'
        b'event: token\ndata: {"delta": "lo"}\n\n'
        b'event: done\ndata: {"conversation_id": "c1", "model": "gemma4:e2b", '
        b'"provider": "ollama"}\n\n'
    )
    client = _client_with_sse_body(body)
    try:
        text, done = stream_chat_response(client, "http://testserver", None, "hi", None)
    finally:
        client.close()

    assert text == "Hello"
    assert done == {"conversation_id": "c1", "model": "gemma4:e2b", "provider": "ollama"}
    assert "Hello" in capsys.readouterr().out


def test_stream_chat_response_raises_chat_error_on_error_event() -> None:
    body = b'event: error\ndata: {"error": "local model unavailable"}\n\n'
    client = _client_with_sse_body(body)
    try:
        with pytest.raises(ChatError, match="local model unavailable"):
            stream_chat_response(client, "http://testserver", None, "hi", None)
    finally:
        client.close()


def test_stream_chat_response_raises_chat_error_on_http_error_status() -> None:
    body = b'{"detail": "cloud provider not configured"}'
    client = _client_with_sse_body(body, status_code=501)
    try:
        with pytest.raises(ChatError, match="cloud provider not configured"):
            stream_chat_response(client, "http://testserver", None, "hi", False)
    finally:
        client.close()
