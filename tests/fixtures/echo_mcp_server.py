#!/usr/bin/env python3
"""Minimal stdio MCP server, used only by apps/api/tests/test_mcp_adapter.py
to exercise MCPAdapter.connect_stdio against a real MCP server process
(not a mock) over real stdio process-to-process communication.
"""

from mcp.server import MCPServer

app = MCPServer("echo-test-server")


@app.tool()
def echo(text: str) -> str:
    """Return the input text unchanged."""
    return text


if __name__ == "__main__":
    app.run(transport="stdio")
