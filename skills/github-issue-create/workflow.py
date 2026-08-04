"""Workflow for the github-issue-create Skill (SPEC.md §6.7 Skill Protocol,
§12.1 MEDIUM risk — "Issue 생성 → 승인").

Wraps personal_ai.tools.github_write.GithubCreateIssueTool /
GithubCloseIssueTool. Unlike the read-only lookup Skills
(github-issues-lookup, local-file-search), `verify` here trusts execute()'s
own success/error instead of flipping success based on evidence being
empty — a create call that genuinely fails already reports success=False
from execute(), so there's nothing for verify() to second-guess.
"""

from __future__ import annotations

import json

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.github_write import GithubCloseIssueTool, GithubCreateIssueTool


def _tool_context(context: SkillContext) -> ToolContext:
    return ToolContext(
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        project_id=context.project_id,
        workspace_id=context.workspace_id,
        granted_scopes=context.granted_scopes,
    )


class GithubIssueCreateSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "github.create_issue",
                "arguments": arguments,
            }
        ]

    async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
        result = await GithubCreateIssueTool().execute(arguments, _tool_context(context))
        repo = arguments.get("repo", "?")

        rollback_token = None
        if result.success and result.data:
            number = result.data.get("number")
            if number is not None:
                rollback_token = json.dumps({"repo": repo, "issue_number": number})

        summary = (
            f"Created issue #{result.data.get('number')} in {repo}"
            if result.success and result.data
            else f"Failed to create issue in {repo}"
        )
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            rollback_token=rollback_token,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        payload = json.loads(rollback_token)
        repo = payload["repo"]
        issue_number = payload["issue_number"]

        result = await GithubCloseIssueTool().execute(
            {"repo": repo, "issue_number": issue_number}, _tool_context(context)
        )
        summary = (
            f"Rolled back: closed issue #{issue_number} in {repo}"
            if result.success
            else f"Rollback failed for issue #{issue_number} in {repo}"
        )
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )
