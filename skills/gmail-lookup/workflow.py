"""Workflow for the gmail-lookup Skill (SPEC.md §6.7 Skill Protocol).

Thin wrapper around personal_ai.tools.gmail.GmailSearchTool: this Skill's
whole job is turning a single read-only Tool call into a policy-checked
Skill result, so plan/execute/verify/rollback stay minimal by design (see
SKILL.md for the full contract).
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.gmail import GmailSearchTool


class GmailLookupSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "gmail.search_messages",
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
        result = await GmailSearchTool().execute(arguments, tool_context)
        messages = (result.data or {}).get("messages", [])
        summary = f"{len(messages)}개 메일 확인됨" if result.success else "Gmail 조회 실패"
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        # Zero matching messages is a valid outcome, not a failure.
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
