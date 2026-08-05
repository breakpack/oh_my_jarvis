"""Unit tests for chat.get_model_provider's local-vs-cloud routing logic
(SPEC.md §11.3): a "deepseek*" model name routes to DeepSeekProvider,
anything else (or no model) routes to OllamaProvider.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from personal_ai_api import chat as chat_module
from personal_ai_api.chat import ChatRequest, get_model_provider
from personal_ai_api.main import app

from personal_ai.models.providers import DeepSeekProvider, OllamaProvider


def _request(**overrides) -> ChatRequest:
    return ChatRequest(conversation_id=None, message="hi", **overrides)


def test_no_model_routes_to_ollama_default():
    provider = get_model_provider(_request())

    assert isinstance(provider, OllamaProvider)
    assert provider.model == chat_module.settings.ollama_local_fast_model


def test_ollama_model_name_routes_to_ollama():
    provider = get_model_provider(_request(model="qwen2.5:1.5b"))

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:1.5b"


def test_deepseek_model_routes_to_deepseek_when_configured(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "test-key")

    provider = get_model_provider(_request(model="deepseek-chat"))

    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "deepseek-chat"


def test_deepseek_model_without_api_key_raises_400(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", None)

    with pytest.raises(HTTPException) as exc_info:
        get_model_provider(_request(model="deepseek-chat"))

    assert exc_info.value.status_code == 400
    assert "DEEPSEEK_API_KEY" in exc_info.value.detail


def test_deepseek_model_with_local_only_raises_400(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "test-key")

    with pytest.raises(HTTPException) as exc_info:
        get_model_provider(_request(model="deepseek-chat", local_only=True))

    assert exc_info.value.status_code == 400
    assert "local_only" in exc_info.value.detail


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, response_by_url_suffix, raise_for_suffix=None):
        self._by_suffix = response_by_url_suffix
        self._raise_for_suffix = raise_for_suffix or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        for suffix, exc in self._raise_for_suffix.items():
            if url.endswith(suffix):
                raise exc
        for suffix, response in self._by_suffix.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected URL: {url}")


def test_list_models_returns_ollama_only_when_deepseek_unconfigured(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", None)
    fake_client = _FakeAsyncClient(
        {"/api/tags": _FakeResponse({"models": [{"name": "gemma4:e2b", "size": 123}]})}
    )
    monkeypatch.setattr(chat_module.httpx, "AsyncClient", lambda **kwargs: fake_client)

    response = TestClient(app).get("/api/v1/models")

    assert response.status_code == 200
    assert response.json() == [{"name": "gemma4:e2b", "size": 123}]


def test_list_models_merges_deepseek_when_configured(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "test-key")
    fake_client = _FakeAsyncClient(
        {
            "/api/tags": _FakeResponse({"models": [{"name": "gemma4:e2b", "size": 123}]}),
            "/models": _FakeResponse({"data": [{"id": "deepseek-chat"}]}),
        }
    )
    monkeypatch.setattr(chat_module.httpx, "AsyncClient", lambda **kwargs: fake_client)

    response = TestClient(app).get("/api/v1/models")

    assert response.status_code == 200
    names = {m["name"] for m in response.json()}
    assert names == {"gemma4:e2b", "deepseek-chat"}


def test_list_models_ollama_down_still_returns_deepseek_models(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "test-key")
    fake_client = _FakeAsyncClient(
        {"/models": _FakeResponse({"data": [{"id": "deepseek-chat"}]})},
        raise_for_suffix={"/api/tags": httpx.ConnectError("boom")},
    )
    monkeypatch.setattr(chat_module.httpx, "AsyncClient", lambda **kwargs: fake_client)

    response = TestClient(app).get("/api/v1/models")

    assert response.status_code == 200
    assert response.json() == [{"name": "deepseek-chat", "size": None}]


def test_list_models_deepseek_down_still_returns_ollama_models(monkeypatch):
    monkeypatch.setattr(chat_module.settings, "deepseek_api_key", "test-key")
    fake_client = _FakeAsyncClient(
        {"/api/tags": _FakeResponse({"models": [{"name": "gemma4:e2b", "size": 123}]})},
        raise_for_suffix={"/models": httpx.ConnectError("boom")},
    )
    monkeypatch.setattr(chat_module.httpx, "AsyncClient", lambda **kwargs: fake_client)

    response = TestClient(app).get("/api/v1/models")

    assert response.status_code == 200
    assert response.json() == [{"name": "gemma4:e2b", "size": 123}]
