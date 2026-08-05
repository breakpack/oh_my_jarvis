"""Ollama embedding provider (SPEC.md §8.5 RAG pipeline Embed stage).

Mirrors personal_ai.models.providers.OllamaProvider's error-handling
pattern: a failed call raises ModelProviderError with a message safe to
show the user, so a document upload failure has a clear, visible cause
instead of silently producing zero vectors.
"""

from __future__ import annotations

import httpx

from personal_ai.models.providers import ModelProviderError, normalize_keep_alive


class OllamaEmbeddingProvider:
    def __init__(
        self, base_url: str, model: str, timeout: float = 60.0, keep_alive: int | str = "-1"
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        # Same reasoning as OllamaProvider: keeps the embedding model resident
        # instead of reloading it 5m after the last document/search.
        self._keep_alive = normalize_keep_alive(keep_alive)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": texts, "keep_alive": self._keep_alive}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/embed", json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(
                f"Ollama returned an error ({exc.response.status_code}) for embedding "
                f"model '{self.model}'."
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                f"Could not reach Ollama at {self._base_url}. Is it running?"
            ) from exc

        embeddings = response.json().get("embeddings")
        if not embeddings:
            raise ModelProviderError(f"Ollama returned no embeddings for model '{self.model}'.")
        return embeddings
