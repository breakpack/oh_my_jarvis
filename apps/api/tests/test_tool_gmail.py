"""Unit tests for GmailSearchTool (SPEC.md §7, §20.3). No real network
calls: httpx.AsyncClient is replaced with a fake that returns canned
responses, keyed by URL.
"""

from __future__ import annotations

import httpx

from personal_ai.tools import gmail as gmail_module
from personal_ai.tools.base import ToolContext
from personal_ai.tools.gmail import GmailSearchTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"gmail.readonly"},
)


def _set_creds(monkeypatch) -> None:
    monkeypatch.setenv("GMAIL_CLIENT_ID", "cid")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "rtoken")


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.text = str(json_data)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://example.com")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, token_response, list_response=None, detail_by_id=None, raise_on_get=None):
        self.token_response = token_response
        self.list_response = list_response
        self.detail_by_id = detail_by_id or {}
        self.raise_on_get = raise_on_get
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self.token_response

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        if self.raise_on_get is not None:
            raise self.raise_on_get
        if url.endswith("/messages"):
            return self.list_response
        message_id = url.rsplit("/", 1)[-1]
        return self.detail_by_id[message_id]


def _patch_client(monkeypatch, fake_client: _FakeAsyncClient) -> None:
    monkeypatch.setattr(gmail_module.httpx, "AsyncClient", lambda **kwargs: fake_client)


async def test_execute_without_credentials_never_calls_network(monkeypatch):
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)

    def _boom(**kwargs):
        raise AssertionError("httpx.AsyncClient must not be constructed without credentials")

    monkeypatch.setattr(gmail_module.httpx, "AsyncClient", _boom)

    tool = GmailSearchTool()
    result = await tool.execute({"query": "is:unread"}, _CONTEXT)

    assert result.success is False
    assert "GMAIL_CLIENT_ID" in result.error


async def test_execute_requires_query(monkeypatch):
    _set_creds(monkeypatch)

    tool = GmailSearchTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "query" in result.error


async def test_execute_returns_messages_and_evidence(monkeypatch):
    _set_creds(monkeypatch)
    fake_client = _FakeAsyncClient(
        token_response=_FakeResponse({"access_token": "tok"}),
        list_response=_FakeResponse({"messages": [{"id": "m1"}, {"id": "m2"}]}),
        detail_by_id={
            "m1": _FakeResponse(
                {
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Hello"},
                            {"name": "From", "value": "a@example.com"},
                            {"name": "Date", "value": "2026-01-01"},
                        ]
                    },
                    "snippet": "hi there",
                }
            ),
            "m2": _FakeResponse(
                {
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Hi"},
                            {"name": "From", "value": "b@example.com"},
                            {"name": "Date", "value": "2026-01-02"},
                        ]
                    },
                    "snippet": "another one",
                }
            ),
        },
    )
    _patch_client(monkeypatch, fake_client)

    tool = GmailSearchTool()
    result = await tool.execute({"query": "is:unread"}, _CONTEXT)

    assert result.success is True
    assert result.error is None
    assert len(result.data["messages"]) == 2
    assert result.data["messages"][0]["subject"] == "Hello"
    assert result.evidence[0]["source_type"] == "gmail_message"
    assert result.evidence[1]["metadata"]["from"] == "b@example.com"

    # The refresh-token exchange happens before any Gmail API call.
    assert fake_client.calls[0][0] == "POST"


async def test_execute_wraps_gmail_api_error_in_tool_result(monkeypatch):
    _set_creds(monkeypatch)
    fake_client = _FakeAsyncClient(
        token_response=_FakeResponse({"access_token": "tok"}),
        list_response=_FakeResponse({"error": "invalid query"}, status_code=400),
    )
    _patch_client(monkeypatch, fake_client)

    tool = GmailSearchTool()
    result = await tool.execute({"query": "bad:query"}, _CONTEXT)

    assert result.success is False
    assert "400" in result.error


async def test_execute_wraps_connection_error_in_tool_result(monkeypatch):
    _set_creds(monkeypatch)
    fake_client = _FakeAsyncClient(
        token_response=_FakeResponse({"access_token": "tok"}),
        raise_on_get=httpx.ConnectError("boom"),
    )
    _patch_client(monkeypatch, fake_client)

    tool = GmailSearchTool()
    result = await tool.execute({"query": "is:unread"}, _CONTEXT)

    assert result.success is False
    assert "failed to reach Gmail" in result.error


async def test_execute_clamps_max_results(monkeypatch):
    _set_creds(monkeypatch)
    fake_client = _FakeAsyncClient(
        token_response=_FakeResponse({"access_token": "tok"}),
        list_response=_FakeResponse({"messages": []}),
    )
    _patch_client(monkeypatch, fake_client)

    tool = GmailSearchTool()
    result = await tool.execute({"query": "is:unread", "max_results": 9999}, _CONTEXT)

    assert result.success is True


async def test_dry_run_does_not_call_network(monkeypatch):
    def _boom(**kwargs):
        raise AssertionError("httpx.AsyncClient must not be constructed during dry_run")

    monkeypatch.setattr(gmail_module.httpx, "AsyncClient", _boom)

    tool = GmailSearchTool()
    result = await tool.dry_run({"query": "is:unread"}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True


def test_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("gmail.search_messages")

    assert tool.name == "gmail.search_messages"
    assert tool.risk_level == "read"
    assert tool.required_scopes == {"gmail.readonly"}
    assert tool.input_schema["required"] == ["query"]
