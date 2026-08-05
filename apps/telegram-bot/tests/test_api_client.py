import httpx
import pytest
from personal_ai_telegram.api_client import ApiError, stream_chat


def _client(sse_body: bytes, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=sse_body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_stream_chat_collects_tokens_and_done_payload() -> None:
    body = (
        b'event: token\ndata: {"delta": "Hello"}\n\n'
        b'event: token\ndata: {"delta": " world"}\n\n'
        b'event: done\ndata: {"conversation_id": "c1", "model": "m1"}\n\n'
    )
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    async with _client(body) as client:
        done = await stream_chat(client, "http://testserver", None, "hi", None, on_delta)

    assert deltas == ["Hello", " world"]
    assert done == {"conversation_id": "c1", "model": "m1"}


@pytest.mark.asyncio
async def test_stream_chat_raises_on_error_event() -> None:
    body = b'event: error\ndata: {"error": "boom"}\n\n'

    async def on_delta(delta: str) -> None:
        pass

    async with _client(body) as client:
        with pytest.raises(ApiError, match="boom"):
            await stream_chat(client, "http://testserver", None, "hi", None, on_delta)


@pytest.mark.asyncio
async def test_stream_chat_raises_on_http_error_status() -> None:
    async def on_delta(delta: str) -> None:
        pass

    async with _client(b'{"detail": "not found"}', status_code=404) as client:
        with pytest.raises(ApiError, match="not found"):
            await stream_chat(client, "http://testserver", None, "hi", None, on_delta)
