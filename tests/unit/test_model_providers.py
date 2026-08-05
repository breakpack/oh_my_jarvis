"""Unit tests for personal_ai.models.providers.normalize_keep_alive.

Ollama's duration parser rejects a bare numeric string like "-1" (it wants
a unit, e.g. "30m") but accepts a JSON number -1 to mean "never unload" —
this is the one non-trivial branch in the keep_alive plumbing.
"""

from __future__ import annotations

import pytest

from personal_ai.knowledge.embeddings import OllamaEmbeddingProvider
from personal_ai.models.providers import OllamaProvider, normalize_keep_alive


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
