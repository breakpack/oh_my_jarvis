"""Model provider layer (SPEC.md §11.1 ModelProvider protocol).

Only the Ollama-backed local provider is implemented in this phase; cloud
providers are added when Phase 5+ needs them (SPEC.md §11.3).
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


class ModelProvider(Protocol):
    model: str
    provider_name: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[str]: ...


class OllamaProvider:
    """Local-first provider backed by an Ollama server's streaming chat API."""

    provider_name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    async def generate(self, request: ModelRequest) -> ModelResponse:
        content = "".join([chunk async for chunk in self.stream(request)])
        return ModelResponse(content=content, model=self.model, provider=self.provider_name)

    async def stream(self, request: ModelRequest) -> AsyncIterator[str]:
        payload = {"model": self.model, "messages": request.messages, "stream": True}
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
