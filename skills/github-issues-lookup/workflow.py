"""Workflow for the github-issues-lookup Skill (SPEC.md §6.7 Skill Protocol).

Thin wrapper around personal_ai.tools.github.GithubIssuesTool: this Skill's
whole job is turning a single read-only Tool call into a policy-checked,
evidence-verified Skill result, so plan/execute/verify/rollback stay minimal
by design (see SKILL.md for the full contract).
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.github import GithubIssuesTool


class GithubIssuesLookupSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "github.list_issues",
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
        result = await GithubIssuesTool().execute(arguments, tool_context)
        issues = (result.data or {}).get("issues", [])
        repo = arguments.get("repo", "?")
        return SkillResult(
            success=result.success,
            summary=f"Found {len(issues)} issues in {repo}",
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        # An empty result set is a valid outcome (e.g. zero open issues), not a failure —
        # only the underlying tool call's own success/error should determine this.
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
