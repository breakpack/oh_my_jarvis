"""Integration test for MCPAdapter (SPEC.md §7.2) against a real MCP server
process communicating over stdio — not mocked. No network or credentials
needed: tests/fixtures/echo_mcp_server.py is launched as a subprocess with
the same Python interpreter running the tests.
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from personal_ai.mcp.adapter import MCPAdapter, MCPToolAdapter
from personal_ai.tools.base import ToolContext

_FIXTURE_SERVER = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "echo_mcp_server.py"

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes=set(),
)


@asynccontextmanager
async def _connect_echo_server():
    # anyio's stdio_client uses a task-group-based context manager, which
    # must be entered and exited from the same asyncio Task — so connect,
    # use, and close all happen inline within one test function's task
    # rather than being split across a pytest fixture's yield boundary.
    adapter = MCPAdapter()
    try:
        tools = await adapter.connect_stdio([sys.executable, str(_FIXTURE_SERVER)])
        yield tools
    finally:
        await adapter.close()


async def test_connect_stdio_discovers_the_echo_tool():
    async with _connect_echo_server() as tools:
        assert len(tools) == 1
        tool = tools[0]

        assert isinstance(tool, MCPToolAdapter)
        assert tool.name == "echo"
        assert "unchanged" in tool.description.lower()
        assert tool.input_schema["type"] == "object"
        assert "text" in tool.input_schema["properties"]
        # Risk Classification (SPEC §7.2): MCP tools carry no risk metadata
        # of their own, so the adapter must default to a non-autonomous level.
        assert tool.risk_level == "confirm"
        assert tool.required_scopes == set()


async def test_execute_calls_the_real_server_and_returns_its_output():
    async with _connect_echo_server() as tools:
        result = await tools[0].execute({"text": "hello from the test"}, _CONTEXT)

        assert result.success is True
        assert result.error is None
        assert result.data["content"] == ["hello from the test"]


async def test_dry_run_does_not_call_the_server():
    async with _connect_echo_server() as tools:
        result = await tools[0].dry_run({"text": "not sent"}, _CONTEXT)

        assert result.success is True
        assert result.metadata["dry_run"] is True
        assert "not sent" in result.data["preview"]


async def test_execute_with_invalid_arguments_reports_failure_not_a_crash():
    async with _connect_echo_server() as tools:
        result = await tools[0].execute({"wrong_argument_name": "x"}, _CONTEXT)

        assert result.success is False
        assert result.error


async def test_connect_stdio_rejects_empty_command():
    adapter = MCPAdapter()
    with pytest.raises(ValueError, match="non-empty"):
        await adapter.connect_stdio([])
