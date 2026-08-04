"""MCP client adapter (SPEC.md §7.2): connects to an MCP server over stdio
and wraps each MCP tool it finds as an AssistantTool, following the
Schema Validation → Description Normalization → Risk Classification →
Scope Mapping → Internal Tool Registry pipeline described there.

MCP itself is only the connection standard (SPEC §5.2 "MCP = 연결 표준");
this module never hands an MCP tool straight to the model — everything
routes through the AssistantTool shape the rest of the app already speaks.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import mcp
import mcp.types as mcp_types
from mcp.client.stdio import stdio_client

from personal_ai.tools.base import AssistantTool, ToolContext, ToolResult

# MCP tools carry no risk metadata of their own; SPEC §12.1 puts "외부
# 서비스" actions at MEDIUM ("승인"), so default every adapted tool to
# "confirm" until a policy layer overrides it per named tool.
DEFAULT_RISK_LEVEL = "confirm"


def _normalize_description(mcp_tool: mcp_types.Tool) -> str:
    description = (mcp_tool.description or "").strip()
    return description or f"MCP tool '{mcp_tool.name}' (no description provided by the server)."


def _classify_risk(mcp_tool: mcp_types.Tool) -> str:
    return DEFAULT_RISK_LEVEL


def _map_scopes(mcp_tool: mcp_types.Tool) -> set[str]:
    # No scope metadata in the MCP tool spec — granting/checking scopes is
    # the Policy Engine's job (SPEC §3.5), not this adapter's.
    return set()


def _content_to_text(item: Any) -> str:
    text = getattr(item, "text", None)
    return text if text is not None else str(item)


class MCPToolAdapter:
    """AssistantTool backed by a single tool on a live MCP ClientSession."""

    def __init__(
        self,
        session: mcp.ClientSession,
        name: str,
        description: str,
        input_schema: dict,
        risk_level: str = DEFAULT_RISK_LEVEL,
        required_scopes: set[str] | None = None,
    ) -> None:
        self._session = session
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.risk_level = risk_level
        self.required_scopes = required_scopes or set()

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        return ToolResult(
            success=True,
            data={"preview": f"Would call MCP tool '{self.name}' with arguments {arguments}"},
            metadata={"dry_run": True},
        )

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        try:
            result = await self._session.call_tool(self.name, arguments)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

        content = [_content_to_text(item) for item in result.content]
        return ToolResult(
            success=not result.is_error,
            data={"content": content, "structured_content": result.structured_content},
            error="\n".join(content) if result.is_error else None,
        )

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        return result


class MCPAdapter:
    """Owns one stdio MCP server connection for the lifetime of the adapter.

    The connection is kept open (via an internal AsyncExitStack) past the
    return of `connect_stdio`, because the AssistantTool objects it returns
    call back into the same session later. Call `close()` (or use the
    adapter as an async context manager) to tear it down.
    """

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._session: mcp.ClientSession | None = None

    async def connect_stdio(self, command: list[str]) -> list[AssistantTool]:
        if not command:
            raise ValueError("command must be a non-empty argument array")

        # SPEC §20.3: argument array, never shell=True.
        server_params = mcp.StdioServerParameters(command=command[0], args=list(command[1:]))
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await self._exit_stack.enter_async_context(
            mcp.ClientSession(read_stream, write_stream)
        )
        await session.initialize()
        self._session = session

        tools_result = await session.list_tools()

        adapted: list[AssistantTool] = []
        for mcp_tool in tools_result.tools:
            # Schema Validation: the MCP tool's JSON Schema is already
            # well-formed by protocol contract — carried through as-is.
            adapted.append(
                MCPToolAdapter(
                    session=session,
                    name=mcp_tool.name,
                    description=_normalize_description(mcp_tool),  # Description Normalization
                    input_schema=mcp_tool.input_schema,
                    risk_level=_classify_risk(mcp_tool),  # Risk Classification
                    required_scopes=_map_scopes(mcp_tool),  # Scope Mapping
                )
                # -> Internal Tool Registry: the caller registers these
                # (e.g. into personal_ai.tools.registry.default_tool_registry).
            )
        return adapted

    async def close(self) -> None:
        await self._exit_stack.aclose()
        self._session = None

    async def __aenter__(self) -> MCPAdapter:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
