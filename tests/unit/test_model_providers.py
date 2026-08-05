"""Unit tests for personal_ai.models.providers: normalize_keep_alive (Ollama's
duration parser rejects a bare numeric string like "-1", it wants a unit
e.g. "30m", but accepts a JSON number -1 to mean "never unload") and
DeepSeekProvider's OpenAI-compatible SSE stream parsing.
"""

from __future__ import annotations

import httpx
import pytest

from personal_ai.knowledge.embeddings import OllamaEmbeddingProvider
from personal_ai.models.providers import (
    DeepSeekProvider,
    ModelProviderError,
    ModelRequest,
    OllamaProvider,
    normalize_keep_alive,
)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("-1", -1),
        ("0", 0),
        ("300", 300),
        (-1, -1),
        ("30m", "30m"),
        ("24h", "24h"),
    ],
)
def test_normalize_keep_alive(value, expected):
    assert normalize_keep_alive(value) == expected


def test_ollama_provider_normalizes_keep_alive_on_init():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", keep_alive="-1")
    assert provider._keep_alive == -1


def test_ollama_provider_passes_through_duration_string():
    provider = OllamaProvider(base_url="http://localhost:11434", model="m", keep_alive="30m")
    assert provider._keep_alive == "30m"


def test_ollama_embedding_provider_normalizes_keep_alive_on_init():
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="m", keep_alive="-1"
    )
    assert provider._keep_alive == -1


class _FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamContextManager:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    def __init__(self, response=None, raise_on_stream=None):
        self._response = response
        self._raise_on_stream = raise_on_stream

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        if self._raise_on_stream is not None:
            raise self._raise_on_stream
        return _FakeStreamContextManager(self._response)


def _patch_client(monkeypatch, fake_client) -> None:
    import personal_ai.models.providers as providers_module

    monkeypatch.setattr(providers_module.httpx, "AsyncClient", lambda **kwargs: fake_client)


async def test_deepseek_provider_streams_tokens_and_stops_at_done(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        'data: {"choices":[{"delta":{"content":" world"}}]}',
        "data: [DONE]",
    ]
    _patch_client(monkeypatch, _FakeAsyncClient(_FakeStreamResponse(lines)))

    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    deltas = [chunk async for chunk in provider.stream(ModelRequest(messages=[]))]

    assert deltas == ["Hello", " world"]


async def test_deepseek_provider_ignores_non_data_lines(monkeypatch):
    lines = [
        "",
        ": comment",
        'data: {"choices":[{"delta":{"content":"Hi"}}]}',
        "data: [DONE]",
    ]
    _patch_client(monkeypatch, _FakeAsyncClient(_FakeStreamResponse(lines)))

    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    deltas = [chunk async for chunk in provider.stream(ModelRequest(messages=[]))]

    assert deltas == ["Hi"]


async def test_deepseek_provider_raises_on_http_status_error(monkeypatch):
    lines = ['data: {"choices":[]}']
    _patch_client(monkeypatch, _FakeAsyncClient(_FakeStreamResponse(lines, status_code=401)))

    provider = DeepSeekProvider(api_key="bad-key", model="deepseek-chat")
    with pytest.raises(ModelProviderError, match="401"):
        async for _ in provider.stream(ModelRequest(messages=[])):
            pass


async def test_deepseek_provider_raises_on_connection_error(monkeypatch):
    _patch_client(monkeypatch, _FakeAsyncClient(raise_on_stream=httpx.ConnectError("boom")))

    provider = DeepSeekProvider(api_key="k", model="deepseek-chat")
    with pytest.raises(ModelProviderError, match="DeepSeek"):
        async for _ in provider.stream(ModelRequest(messages=[])):
            pass
