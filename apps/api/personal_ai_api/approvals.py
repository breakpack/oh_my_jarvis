"""Approvals API (SPEC.md §12 Policy/Approval, §20.4 Audit).

The one action shape this phase produces approvals for is a gated skill run
(action="skill:<name>", created by skills.py when the skill's manifest risk
level requires approval). Approving replays that skill's plan/execute/verify
sequence for real; rejecting just flips its status.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

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

router = APIRouter(prefix="/api/v1", tags=["approvals"])

SKILL_ACTION_PREFIX = "skill:"


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

    if not approval.action.startswith(SKILL_ACTION_PREFIX):
        raise HTTPException(status_code=400, detail="unsupported approval action")
    skill_name = approval.action[len(SKILL_ACTION_PREFIX) :]

    started = time.monotonic()
    result = await _execute_skill_for_approval(skill_name, approval.arguments, user_id)

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
