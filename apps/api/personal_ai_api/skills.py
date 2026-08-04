"""Skills API (SPEC.md §6.5 Skill lifecycle, §6.6 Resolver, §15 Skills,
§20.4 Audit).

GET /skills/{name}/audit is exposed as a GET (per this phase's brief) even
though SPEC.md §15 lists it as POST — reading an audit trail has no side
effect, so GET is the correct verb; kept here as a deliberate deviation
rather than a typo.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from personal_ai.skills.registry import LoadedSkill
from personal_ai.skills.sdk import SkillContext, SkillResult
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


@router.post("/skills/{name}/run")
async def run_skill_endpoint(
    name: str,
    payload: SkillRunRequest,
    repository: SkillsRepository = Depends(get_skills_repository),
) -> dict:
    try:
        loaded = get_skill(name)
    except SkillNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc

    if not is_enabled(name):
        raise HTTPException(status_code=409, detail="skill disabled")

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
