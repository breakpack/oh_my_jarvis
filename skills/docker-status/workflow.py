"""Workflow for the docker-status Skill (SPEC.md §6.7 Skill Protocol).

Thin wrapper around personal_ai.tools.docker.DockerStatusTool: on-demand,
read-only Docker container listing — unlike the proactive
DockerHealthSource, this never pushes a notification on its own; it only
runs when a user explicitly invokes it (CLI/API/Telegram).
"""

from __future__ import annotations

from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.tools.base import ToolContext
from personal_ai.tools.docker import DockerStatusTool


class DockerStatusSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {
                "step": "call_tool",
                "tool": "docker.list_containers",
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
        result = await DockerStatusTool().execute(arguments, tool_context)
        if not result.success:
            return SkillResult(
                success=False,
                summary="Docker 상태 조회 실패",
                data=result.data,
                evidence=result.evidence,
                error=result.error,
            )

        containers = (result.data or {}).get("containers", [])
        summary = (
            f"{len(containers)}개 컨테이너 확인됨" if containers else "실행 중인 컨테이너 없음"
        )
        evidence = [
            {"content": f"{c.get('Names', '?')}: {c.get('Status', '?')}"} for c in containers
        ]
        return SkillResult(
            success=True,
            summary=summary,
            data=result.data,
            evidence=evidence,
            error=None,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        # An empty container list is a valid outcome (nothing running), not a failure.
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        return SkillResult(success=True, summary="No rollback needed (read-only)")
