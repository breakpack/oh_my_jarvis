"""Tool interface (SPEC.md §7.1)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ToolContext(BaseModel):
    user_id: str
    conversation_id: str
    project_id: str | None
    workspace_id: str | None
    granted_scopes: set[str]


class ToolResult(BaseModel):
    success: bool
    data: dict | None = None
    evidence: list[dict] = []
    error: str | None = None
    metadata: dict = {}


class AssistantTool(Protocol):
    name: str
    description: str
    input_schema: dict
    risk_level: str
    required_scopes: set[str]

    async def dry_run(
        self,
        arguments: dict,
        context: ToolContext,
    ) -> ToolResult: ...

    async def execute(
        self,
        arguments: dict,
        context: ToolContext,
    ) -> ToolResult: ...

    async def verify(
        self,
        result: ToolResult,
        context: ToolContext,
    ) -> ToolResult: ...
