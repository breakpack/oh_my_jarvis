"""Model provider layer (SPEC.md §11.1 ModelProvider protocol).

OllamaProvider is the local-first provider; DeepSeekProvider is the first
cloud provider (SPEC.md §11.3), used only when a request opts in (not
local_only) and picks a "deepseek*" model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx
from pydantic import BaseModel


class ModelRequest(BaseModel):
    messages: list[dict]
    tools: list[dict] = []
    response_schema: dict | None = None
    temperature: float = 0.2
    local_only: bool = False


class ModelResponse(BaseModel):
    content: str
    tool_calls: list[dict] = []
    usage: dict = {}
    model: str
    provider: str


class ModelProviderError(RuntimeError):
    """Raised when a provider cannot fulfill a request; message is safe to show the user."""


def normalize_keep_alive(value: int | str) -> int | str:
    """Ollama's duration parser requires a unit (e.g. "30m") and rejects a
    bare numeric string like "-1" with "missing unit in duration" — send
    those as a JSON number instead. Duration strings (e.g. "30m") pass
    through unchanged."""
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    return value


class ModelProvider(Protocol):
    model: str
    provider_name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[str]: ...


class OllamaProvider:
    """Local-first provider backed by an Ollama server's streaming chat API."""

    provider_name = "ollama"

    def __init__(
        self, base_url: str, model: str, timeout: float = 60.0, keep_alive: int | str = "-1"
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        # Ollama unloads a model 5m after its last request unless keep_alive says
        # otherwise; -1 keeps it resident indefinitely so chat replies after an
        # idle gap don't pay the reload cost again.
        self._keep_alive = normalize_keep_alive(keep_alive)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        content = "".join([chunk async for chunk in self.stream(request)])
        return ModelResponse(content=content, model=self.model, provider=self.provider_name)

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": request.messages,
            "stream": True,
            "keep_alive": self._keep_alive,
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(
                f"Ollama returned an error ({exc.response.status_code}) for model '{self.model}'."
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                f"Could not reach Ollama at {self._base_url}. Is it running?"
            ) from exc


class DeepSeekProvider:
    """Cloud provider backed by DeepSeek's OpenAI-compatible chat completions
    API (https://api-docs.deepseek.com)."""

    provider_name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    async def generate(self, request: ModelRequest) -> ModelResponse:
        content = "".join([chunk async for chunk in self.stream(request)])
        return ModelResponse(content=content, model=self.model, provider=self.provider_name)

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": request.messages,
            "stream": True,
            "temperature": request.temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content") or ""
                    if delta:
                        yield delta
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(
                f"DeepSeek returned an error ({exc.response.status_code}) for model '{self.model}'."
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                f"Could not reach DeepSeek at {self._base_url}. Check DEEPSEEK_API_KEY "
                "and network access."
            ) from exc
