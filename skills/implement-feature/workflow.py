"""Workflow for the implement-feature Skill (SPEC.md §9.4, §12.1 MEDIUM).

This Skill never commits. It applies a patch inside an isolated,
throwaway git-worktree workspace and (optionally) runs a test command
there — both fully reversible via `destroy_workspace`. The actual
`git add` + `git commit` only happens later, in apps/api's approval flow,
against the same workspace this Skill leaves behind on success.
"""

from __future__ import annotations

from personal_ai.development.workspace import GitWorktreeRuntime
from personal_ai.skills.sdk import SkillContext, SkillResult


class ImplementFeatureSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        steps = [
            {"step": "create_workspace", "source": arguments.get("source")},
            {"step": "apply_patch"},
        ]
        if arguments.get("test_command"):
            steps.append({"step": "run_command", "command": arguments["test_command"]})
        steps.append({"step": "get_diff"})
        return steps

    async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
        source = arguments.get("source")
        patch = arguments.get("patch")
        test_command = arguments.get("test_command")

        if not source or not patch:
            return SkillResult(
                success=False,
                summary="source and patch are required",
                error="source and patch are required",
            )

        runtime = GitWorktreeRuntime()
        try:
            workspace_id = await runtime.create_workspace(source)
        except Exception as exc:
            return SkillResult(success=False, summary="Failed to create workspace", error=str(exc))

        patch_result = await runtime.apply_patch(workspace_id, patch)
        if not patch_result["success"]:
            await runtime.destroy_workspace(workspace_id)
            return SkillResult(
                success=False,
                summary="Patch did not apply",
                data={"patch_result": patch_result},
                error=patch_result["stderr"] or "git apply failed",
            )

        test_result = None
        if test_command:
            try:
                test_result = await runtime.run_command(workspace_id, test_command)
            except PermissionError as exc:
                await runtime.destroy_workspace(workspace_id)
                return SkillResult(
                    success=False,
                    summary="Test command not allowed",
                    data={"patch_result": patch_result},
                    error=str(exc),
                )

        diff = await runtime.get_diff(workspace_id)
        tests_passed = test_result is None or test_result["exit_code"] == 0

        summary = "Patch applied"
        if test_result is not None:
            status = "passed" if tests_passed else "failed"
            summary += f"; tests {status} (exit {test_result['exit_code']})"

        # No commit here — the workspace is intentionally left behind
        # (rollback_token=workspace_id) for the approval flow to commit
        # into, or for rollback() to destroy if the change is rejected.
        return SkillResult(
            success=tests_passed,
            summary=summary,
            data={
                "workspace_id": workspace_id,
                "diff": diff,
                "patch_result": patch_result,
                "test_result": test_result,
            },
            rollback_token=workspace_id,
        )

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        runtime = GitWorktreeRuntime()
        await runtime.destroy_workspace(rollback_token)
        return SkillResult(
            success=True, summary=f"Rolled back: destroyed workspace {rollback_token}"
        )
