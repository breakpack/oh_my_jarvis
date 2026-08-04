"""Adapter slot for Browser Use (SPEC.md §5.2, §10) — LLM-driven
exploratory browsing.

Not installed in this MVP, same pattern as personal_ai/knowledge/parsers.py's
DoclingParser: Playwright (personal_ai/browser/playwright_runtime.py)
already covers the deterministic-workflow path SPEC §10 needs now; Browser
Use is for open-ended "figure out how to do X on this site" exploration,
which this Phase doesn't need. This class exists only to reserve the
AssistantTool-shaped seam so a real adapter can be dropped in later
without any caller changing.
"""

from __future__ import annotations

from personal_ai.tools.base import ToolContext, ToolResult

_NOT_IMPLEMENTED_MESSAGE = (
    "Browser Use adapter — see SPEC.md §5.2/§10, install `browser-use` and implement to "
    "enable exploratory browsing"
)


class BrowserUseAdapter:
    """Same method shape as AssistantTool (SPEC §7.1); every method raises
    NotImplementedError. Intentionally not registered in
    personal_ai.tools.registry.default_tool_registry — there is nothing
    working here yet to register."""

    name = "browser.explore"
    description = _NOT_IMPLEMENTED_MESSAGE
    input_schema: dict = {"type": "object", "properties": {}, "additionalProperties": True}
    risk_level = "medium"
    required_scopes: set[str] = set()

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)
