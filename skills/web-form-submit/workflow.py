"""Workflow for the web-form-submit Skill (SPEC.md §6.7 Skill Protocol,
§10 Browser Mode, §12.1 MEDIUM risk — "폼 제출은 승인").

Wraps personal_ai.tools.browser.BrowserSubmitFormTool. The approval gate
itself lives upstream (manifest.yaml approval.required_before +
risk_level=medium, enforced by Phase 5's Approval Manager before execute()
is ever called) — this Skill does not re-implement it. Unlike the
read-only Skills (web-read, github-issues-lookup), `verify` here trusts
execute()'s own success/error instead of flipping success based on
evidence being empty — a genuinely failed submit already reports
success=False from execute(). Rollback is not supported: form submissions
are a real external side effect with no generic undo.
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.browser import BrowserSubmitFormTool


class WebFormSubmitSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "browser.submit_form",
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
        result = await BrowserSubmitFormTool().execute(arguments, tool_context)
        url = arguments.get("url", "?")
        summary = (
            f"Submitted form at {url}" if result.success else f"Failed to submit form at {url}"
        )
        return SkillResult(
            success=result.success,
            summary=summary,
            data=result.data,
            evidence=result.evidence,
            error=result.error,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(
            success=False,
            summary="Rollback not supported for form submissions",
            error="web-form-submit does not support rollback (irreversible external side effect)",
        )
