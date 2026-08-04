"""Workflow for the web-read Skill (SPEC.md §6.7 Skill Protocol, §10 Browser
Mode, §20.1 Prompt Injection).

Thin wrapper around personal_ai.tools.browser.BrowserExtractTool — same
"one read-only Tool call -> policy-checked evidence-verified Skill result"
shape as github-issues-lookup and local-file-search. This Skill never
calls browser.submit_form; browser.navigate is declared in the manifest's
capabilities but not called directly here, since BrowserExtractTool
already navigates internally within its own Playwright session.
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.browser import BrowserExtractTool


class WebReadSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "browser.extract",
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
        result = await BrowserExtractTool().execute(arguments, tool_context)
        url = arguments.get("url", "?")
        title = (result.data or {}).get("title")
        summary = (
            f"Extracted content from {title or url}"
            if result.success
            else f"Failed to extract content from {url}"
        )
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        if result.success and not result.evidence:
            return SkillResult(
                success=False,
                summary=result.summary,
                data=result.data,
                evidence=result.evidence,
                error="browser.extract succeeded but returned no evidence",
            )
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
