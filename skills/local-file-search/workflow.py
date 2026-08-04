"""Workflow for the local-file-search Skill (SPEC.md §6.7 Skill Protocol).

Thin wrapper around personal_ai.tools.files.LocalFileSearchTool: this
Skill's whole job is turning a single read-only Tool call into a
policy-checked, evidence-verified Skill result, so plan/execute/verify/
rollback stay minimal by design (see SKILL.md for the full contract).
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.files import LocalFileSearchTool


class LocalFileSearchSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "files.search",
                "arguments": arguments,
            }
        ]

    async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
        tool_context = ToolContext(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            project_id=context.project_id,
            workspace_id=context.workspace_id,
            granted_scopes=context.granted_scopes,
        )
        result = await LocalFileSearchTool().execute(arguments, tool_context)
        matches = (result.data or {}).get("matches", [])
        query = arguments.get("query", "?")
        root = arguments.get("root") or "."
        return SkillResult(
            success=result.success,
            summary=f"Found {len(matches)} matches for '{query}' under {root}",
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        # An empty match set is a valid outcome (e.g. no matches found), not a failure —
        # only the underlying tool call's own success/error should determine this.
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
