"""Workflow for the obsidian-lookup Skill (SPEC.md §6.7 Skill Protocol).

Thin wrapper around personal_ai.tools.obsidian.ObsidianSearchTool: this
Skill's whole job is turning a single read-only Tool call into a
policy-checked Skill result, so plan/execute/verify/rollback stay minimal
by design (see SKILL.md for the full contract).
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.obsidian import ObsidianSearchTool


class ObsidianLookupSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "obsidian.search_notes",
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
        result = await ObsidianSearchTool().execute(arguments, tool_context)
        notes = (result.data or {}).get("notes", [])
        if arguments.get("path"):
            summary = f"노트 조회됨: {arguments['path']}" if result.success else "노트 조회 실패"
        else:
            summary = f"{len(notes)}개 노트 확인됨" if result.success else "노트 검색 실패"
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        # Zero matching notes is a valid outcome, not a failure.
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
