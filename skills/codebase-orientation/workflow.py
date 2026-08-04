"""Workflow for the codebase-orientation Skill (SPEC.md §9.4, §19).

Uses only the DevelopmentRuntime protocol's existing methods (SPEC §9.3) —
there's no dedicated "list directory" call, so a broad `search(workspace_id,
"")` doubles as a structure sample: an empty query substring-matches every
filename, so it returns up to the search cap's worth of file paths across
the whole tree.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from personal_ai.development.workspace import GitWorktreeRuntime
from personal_ai.skills.sdk import SkillContext, SkillResult

_README_EXCERPT_CHARS = 400


class CodebaseOrientationSkill:
    manifest: dict = {}

    async def plan(self, arguments: dict, context: SkillContext) -> list[dict]:
        return [
            {"step": "create_workspace", "source": arguments.get("source")},
            {"step": "search", "query": ""},
            {"step": "search", "query": "README"},
            {"step": "read_file", "path": "<README, if found>"},
            {"step": "destroy_workspace"},
        ]

    async def execute(self, arguments: dict, context: SkillContext) -> SkillResult:
        source = arguments.get("source")
        if not source:
            return SkillResult(
                success=False, summary="source is required", error="source is required"
            )

        runtime = GitWorktreeRuntime()
        try:
            workspace_id = await runtime.create_workspace(source)
        except Exception as exc:
            return SkillResult(success=False, summary="Failed to create workspace", error=str(exc))

        try:
            file_sample = await runtime.search(workspace_id, "")
            top_level = sorted({PurePosixPath(m["path"]).parts[0] for m in file_sample})

            readme_matches = await runtime.search(workspace_id, "README")
            readme_path = next(
                (m["path"] for m in readme_matches if m["matched_by"] == "filename"), None
            )
            readme_excerpt = None
            if readme_path:
                content = await runtime.read_file(workspace_id, readme_path)
                readme_excerpt = content[:_README_EXCERPT_CHARS].strip()

            entry_word = "entry" if len(top_level) == 1 else "entries"
            summary = (
                f"{len(file_sample)} file(s) sampled across {len(top_level)} "
                f"top-level {entry_word}: {', '.join(top_level) or 'none'}."
            )
            if readme_excerpt:
                summary += f" README ({readme_path}): {readme_excerpt}"

            evidence = [
                {"source_type": "local_file", "source_id": m["path"], "title": m["path"]}
                for m in file_sample[:10]
            ]

            return SkillResult(
                success=True,
                summary=summary,
                data={
                    "top_level_entries": top_level,
                    "file_sample": file_sample,
                    "readme_path": readme_path,
                    "readme_excerpt": readme_excerpt,
                },
                evidence=evidence,
            )
        finally:
            await runtime.destroy_workspace(workspace_id)

    async def verify(self, result: SkillResult, context: SkillContext) -> SkillResult:
        return result

    async def rollback(self, rollback_token: str, context: SkillContext) -> SkillResult:
        # Read-only Skill — the workspace is already destroyed at the end
        # of execute(), so there's nothing left to undo.
        return SkillResult(success=True, summary="Nothing to roll back (read-only skill)")
