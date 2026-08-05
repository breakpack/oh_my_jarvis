import json

import httpx
import pytest
from personal_ai_cli.main import (
    ApiError,
    build_models_table,
    fetch_models,
)


def _client(status_code: int, body: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(body).encode())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_models_returns_list() -> None:
    models = [{"name": "gemma4:e2b", "size": 7197509549}]
    client = _client(200, models)
    try:
        result = fetch_models(client, "http://testserver")
    finally:
        client.close()

    assert result == models
    table = build_models_table(result)
    assert table.row_count == 1


def test_fetch_models_raises_api_error_on_failure() -> None:
    client = _client(502, {"detail": "Could not reach Ollama"})
    try:
        with pytest.raises(ApiError, match="Could not reach Ollama"):
            fetch_models(client, "http://testserver")
    finally:
        client.close()


def test_build_models_table_formats_size_in_gb() -> None:
    table = build_models_table([{"name": "gemma4:e2b", "size": 7_197_509_549}])
    assert table.row_count == 1


def test_build_models_table_empty() -> None:
    table = build_models_table([])
    assert table.row_count == 0
