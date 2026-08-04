"""Approvals API (SPEC.md §12 Policy/Approval, §20.4 Audit).

Two action shapes reach this phase's approve endpoint:
- A gated skill run (action="skill:<name>", created by skills.py when the
  skill's manifest risk level requires approval). Approving replays that
  skill's plan/execute/verify sequence for real.
- A workspace commit (action="workspace_commit:<workspace_id>", created by
  workspaces.py -- SPEC §25 DoD "승인 전 commit 금지"). Approving runs the
  actual `git add -A` + `git commit -m <message>` in that workspace's
  repository directory; GitWorktreeRuntime deliberately has no commit
  method of its own, so this is the only place a commit happens.
Rejecting either just flips their status, unchanged.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from personal_ai.security.approval import verify_arguments_unchanged
from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai_api.approvals_repository import (
    ApprovalNotFound,
    ApprovalRecord,
    ApprovalsRepository,
    get_approvals_repository,
)
from personal_ai_api.skills_service import SkillNotFound, find_skill_class, get_skill
from personal_ai_api.workspaces import COMMIT_ACTION_PREFIX
from personal_ai_api.workspaces_repository import (
    WorkspaceRecordNotFound,
    WorkspacesRepository,
    get_workspaces_repository,
)

router = APIRouter(prefix="/api/v1", tags=["approvals"])

SKILL_ACTION_PREFIX = "skill:"
_COMMIT_SUBPROCESS_TIMEOUT_SECONDS = 15


class ApprovalOut(BaseModel):
    id: str
    action: str
    target: str
    risk_level: str
    arguments: dict
    arguments_hash: str
    preview: str
    expected_effects: list
    rollback_available: bool
    rollback_token: str | None = None
    status: str
    expires_at: str | None = None
    created_at: str
    updated_at: str


def _to_out(record: ApprovalRecord) -> ApprovalOut:
    return ApprovalOut(**vars(record))


async def _execute_skill_for_approval(
    skill_name: str, arguments: dict, user_id: str
) -> SkillResult:
    try:
        loaded = get_skill(skill_name)
    except SkillNotFound:
        return SkillResult(
            success=False, summary="skill not found", error=f"skill '{skill_name}' not found"
        )

    skill_cls = find_skill_class(loaded)
    if skill_cls is None:
        return SkillResult(
            success=False,
            summary="skill not implemented",
            error=f"skill '{skill_name}' is not yet implemented (stub only)",
        )

    context = SkillContext(
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        project_id=None,
        workspace_id=None,
        local_only=False,
        granted_scopes=set(loaded.manifest.permissions.scopes),
    )
    skill = skill_cls()
    try:
        await skill.plan(arguments, context)
        result = await skill.execute(arguments, context)
        return await skill.verify(result, context)
    except Exception as exc:  # noqa: BLE001 - a skill's own bug must not 500 the approve endpoint
        return SkillResult(success=False, summary="skill execution failed", error=str(exc))


async def _commit_workspace_for_approval(
    workspace_id: str,
    arguments: dict,
    user_id: str,
    workspaces_repository: WorkspacesRepository,
) -> SkillResult:
    message = arguments.get("message", "")
    try:
        workspace = await workspaces_repository.get_workspace(workspace_id, user_id)
    except WorkspaceRecordNotFound:
        return SkillResult(
            success=False,
            summary="workspace not found",
            error=f"workspace '{workspace_id}' not found",
        )

    repository_dir = Path(workspace.workspace_dir) / "repository"

    # SPEC-mandated order: `git add -A` then `git commit -m <message>`,
    # each its own subprocess.run call (shell=False, argument list only).
    add_result = subprocess.run(
        ["git", "add", "-A"],
        cwd=repository_dir,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_COMMIT_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if add_result.returncode != 0:
        return SkillResult(
            success=False,
            summary="git add failed",
            error=add_result.stderr.strip() or "git add failed",
        )

    commit_result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repository_dir,
        shell=False,
        capture_output=True,
        text=True,
        timeout=_COMMIT_SUBPROCESS_TIMEOUT_SECONDS,
    )
    if commit_result.returncode != 0:
        return SkillResult(
            success=False,
            summary="git commit failed",
            error=commit_result.stderr.strip()
            or commit_result.stdout.strip()
            or "git commit failed",
        )

    return SkillResult(success=True, summary=f"Committed to workspace {workspace_id}: {message}")


@router.get("/approvals")
async def list_approvals_endpoint(
    status: str | None = "pending",
    repository: ApprovalsRepository = Depends(get_approvals_repository),
) -> list[ApprovalOut]:
    user_id = await repository.get_or_create_default_user()
    approvals = await repository.list_approvals(user_id, status=status)
    return [_to_out(a) for a in approvals]


@router.post("/approvals/{approval_id}/approve")
async def approve_approval_endpoint(
    approval_id: str,
    repository: ApprovalsRepository = Depends(get_approvals_repository),
    workspaces_repository: WorkspacesRepository = Depends(get_workspaces_repository),
) -> dict:
    user_id = await repository.get_or_create_default_user()
    try:
        approval = await repository.get_approval(approval_id, user_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc

    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"approval is {approval.status}")

    if approval.expires_at is not None:
        expires_at = datetime.fromisoformat(approval.expires_at)
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(UTC).replace(tzinfo=None)
        if expires_at <= datetime.now(UTC).replace(tzinfo=None):
            await repository.update_approval(approval_id, user_id, {"status": "expired"})
            raise HTTPException(status_code=410, detail="approval expired")

    if not verify_arguments_unchanged(approval.arguments, approval.arguments_hash):
        raise HTTPException(
            status_code=409, detail="arguments hash mismatch — approval invalidated"
        )

    started = time.monotonic()
    if approval.action.startswith(SKILL_ACTION_PREFIX):
        skill_name = approval.action[len(SKILL_ACTION_PREFIX) :]
        result = await _execute_skill_for_approval(skill_name, approval.arguments, user_id)
    elif approval.action.startswith(COMMIT_ACTION_PREFIX):
        workspace_id = approval.action[len(COMMIT_ACTION_PREFIX) :]
        result = await _commit_workspace_for_approval(
            workspace_id, approval.arguments, user_id, workspaces_repository
        )
    else:
        raise HTTPException(status_code=400, detail="unsupported approval action")

    await repository.update_approval(
        approval_id, user_id, {"status": "approved", "rollback_token": result.rollback_token}
    )
    await repository.record_audit(
        user_id,
        "approval_execute",
        {
            "approval_id": approval_id,
            "action": approval.action,
            "success": result.success,
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )

    return result.model_dump()


@router.post("/approvals/{approval_id}/reject", status_code=204)
async def reject_approval_endpoint(
    approval_id: str,
    repository: ApprovalsRepository = Depends(get_approvals_repository),
) -> Response:
    user_id = await repository.get_or_create_default_user()
    try:
        approval = await repository.get_approval(approval_id, user_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc

    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"approval is {approval.status}")

    await repository.update_approval(approval_id, user_id, {"status": "rejected"})
    await repository.record_audit(
        user_id, "approval_reject", {"approval_id": approval_id, "action": approval.action}
    )
    return Response(status_code=204)
