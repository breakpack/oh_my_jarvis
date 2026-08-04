"""In-process registry of AssistantTool instances (SPEC.md §7.2 Internal
Tool Registry — the endpoint of the MCP Tool → ... → Internal Tool Registry
pipeline, and where natively-implemented tools register themselves too).
"""

from __future__ import annotations

from personal_ai.tools.base import AssistantTool


class ToolNotFound(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AssistantTool] = {}

    def register(self, tool: AssistantTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> AssistantTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFound(name) from exc

    def list(self) -> list[AssistantTool]:
        return list(self._tools.values())


default_tool_registry = ToolRegistry()
