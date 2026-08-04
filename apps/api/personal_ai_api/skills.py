"""Skills API (SPEC.md §6.5 Skill lifecycle, §6.6 Resolver, §15 Skills,
§20.4 Audit, §12 Policy/Approval).

GET /skills/{name}/audit is exposed as a GET (per this phase's brief) even
though SPEC.md §15 lists it as POST — reading an audit trail has no side
effect, so GET is the correct verb; kept here as a deliberate deviation
rather than a typo.

POST /skills/{name}/run gates medium+/high risk skills behind an approval
(SPEC §25 DoD "승인 전 실행 불가"): it never calls skill.execute() for those,
only skill.plan() to build a human-readable preview of what approving would
do. read/low_write skills keep running immediately, unchanged from Phase 4.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from personal_ai.security.approval import build_approval_request
from personal_ai.security.policy import (
    RestrictedActionError,
    normalize_risk_level,
    requires_approval,
)
from personal_ai.skills.registry import LoadedSkill
from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai_api.approvals_repository import ApprovalsRepository, get_approvals_repository
from personal_ai_api.skills_service import (
    DEFAULT_RESOLVE_TOP_K,
    SkillNotFound,
    SkillsRepository,
    find_skill_class,
    get_skill,
    get_skills_repository,
    is_enabled,
    list_skills,
    set_enabled,
)

router = APIRouter(prefix="/api/v1", tags=["skills"])


class SkillOut(BaseModel):
    name: str
    display_name: str
    version: str
    description: str
    tags: list[str]
    risk_level: str
    enabled: bool


class InvalidSkillOut(BaseModel):
    path: str
    error: str


class SkillListOut(BaseModel):
    skills: list[SkillOut]
    invalid: list[InvalidSkillOut]


class SkillDetailOut(BaseModel):
    name: str
    manifest: dict
    skill_md: dict
    enabled: bool


class SkillEnabledOut(BaseModel):
    name: str
    enabled: bool


class SkillRunRequest(BaseModel):
    arguments: dict = {}
    project_id: str | None = None


class SkillAuditOut(BaseModel):
    id: str
    event_type: str
    payload: dict
    created_at: str


def _to_skill_out(loaded: LoadedSkill) -> SkillOut:
    metadata = loaded.manifest.metadata
    return SkillOut(
        name=loaded.name,
        display_name=metadata.display_name,
        version=metadata.version,
        description=metadata.description,
        tags=metadata.tags,
        risk_level=loaded.manifest.permissions.risk_level,
        enabled=is_enabled(loaded.name),
    )


@router.get("/skills")
async def list_skills_endpoint(
    query: str | None = None, top_k: int = DEFAULT_RESOLVE_TOP_K
) -> SkillListOut:
    skills, errors = list_skills(query, top_k=top_k)
    return SkillListOut(
        skills=[_to_skill_out(s) for s in skills],
        invalid=[InvalidSkillOut(path=path, error=error) for path, error in errors],
    )


@router.get("/skills/{name}")
async def get_skill_endpoint(name: str) -> SkillDetailOut:
    try:
        loaded = get_skill(name)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    return SkillDetailOut(
        name=loaded.name,
        manifest=loaded.manifest.model_dump(),
        skill_md=loaded.skill_md,
        enabled=is_enabled(loaded.name),
    )


@router.post("/skills/{name}/enable")
async def enable_skill_endpoint(name: str) -> SkillEnabledOut:
    try:
        set_enabled(name, True)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    return SkillEnabledOut(name=name, enabled=True)


@router.post("/skills/{name}/disable")
async def disable_skill_endpoint(name: str) -> SkillEnabledOut:
    try:
        set_enabled(name, False)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    return SkillEnabledOut(name=name, enabled=False)


async def _build_approval_preview(
    loaded: LoadedSkill, arguments: dict, context: SkillContext
) -> str:
    skill_cls = find_skill_class(loaded)
    if skill_cls is None:
        return (
            f"No workflow implementation yet for '{loaded.name}'; "
            "approval created ahead of implementation."
        )
    plan_steps = await skill_cls().plan(arguments, context)
    return str(plan_steps)


@router.post("/skills/{name}/run")
async def run_skill_endpoint(
    name: str,
    payload: SkillRunRequest,
    response: Response,
    repository: SkillsRepository = Depends(get_skills_repository),
    approvals_repository: ApprovalsRepository = Depends(get_approvals_repository),
) -> dict:
    try:
        loaded = get_skill(name)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc

    if not is_enabled(name):
        raise HTTPException(status_code=409, detail="skill disabled")

    risk_level = normalize_risk_level(loaded.manifest.permissions.risk_level)
    try:
        approval_needed = requires_approval(risk_level)
    except RestrictedActionError as exc:
        raise HTTPException(
            status_code=403, detail="action is restricted and cannot be executed"
        ) from exc

    skill_cls = None
    if not approval_needed:
        skill_cls = find_skill_class(loaded)
        if skill_cls is None:
            raise HTTPException(
                status_code=501, detail=f"skill '{name}' is not yet implemented (stub only)"
            )

    user_id = await repository.get_or_create_default_user()
    context = SkillContext(
        user_id=user_id,
        conversation_id=str(uuid.uuid4()),
        project_id=payload.project_id,
        workspace_id=None,
        local_only=False,
        granted_scopes=set(loaded.manifest.permissions.scopes),
    )

    if approval_needed:
        # SPEC §25 DoD "승인 전 실행 불가": skill.execute() must never be
        # called on this path, only plan() (read-only, for the preview).
        preview = await _build_approval_preview(loaded, payload.arguments, context)
        target = str(payload.arguments.get("repo") or name)
        expected_effects = [f"Executes {name} with {risk_level} risk"]
        rollback_available = bool(loaded.manifest.rollback and loaded.manifest.rollback.supported)

        approval_request, arguments_hash = build_approval_request(
            action=f"skill:{name}",
            target=target,
            risk_level=risk_level,
            arguments=payload.arguments,
            preview=preview,
            expected_effects=expected_effects,
            rollback_available=rollback_available,
        )
        expires_at = (
            datetime.fromisoformat(approval_request.expires_at).replace(tzinfo=None)
            if approval_request.expires_at
            else None
        )
        approval = await approvals_repository.create_approval(
            user_id=user_id,
            action=approval_request.action,
            target=approval_request.target,
            risk_level=approval_request.risk_level,
            arguments=approval_request.arguments,
            arguments_hash=arguments_hash,
            preview=approval_request.preview,
            expected_effects=approval_request.expected_effects,
            rollback_available=approval_request.rollback_available,
            expires_at=expires_at,
        )
        response.status_code = 202
        return {"status": "pending_approval", "approval_id": approval.id}

    assert skill_cls is not None  # not approval_needed => resolved above, else 501 already raised
    started = time.monotonic()
    skill = skill_cls()
    try:
        await skill.plan(payload.arguments, context)
        result = await skill.execute(payload.arguments, context)
        result = await skill.verify(result, context)
    except Exception as exc:  # noqa: BLE001 - a skill's own bug must not 500 the endpoint
        result = SkillResult(success=False, summary="skill execution failed", error=str(exc))

    await repository.record_audit(
        user_id,
        "skill_run",
        {
            "skill": name,
            "success": result.success,
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )

    return result.model_dump()


@router.get("/skills/{name}/audit")
async def get_skill_audit_endpoint(
    name: str,
    repository: SkillsRepository = Depends(get_skills_repository),
) -> list[SkillAuditOut]:
    try:
        get_skill(name)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    events = await repository.list_skill_audit(name)
    return [SkillAuditOut(**event) for event in events]
