"""Skill Store API (SPEC.md §6.8 Skill Store, §25 DoD "악성 Skill 차단
테스트", "권한 Preview", "버전 Rollback").

POST /skills/install is the actual enforcement point for "악성 Skill 차단":
audit_skill() runs before a single file is copied, and a failing audit
(audit.passed is False) rejects the install outright -- install_skill_files
/ activate_skill_version are never reached on that path. The same call's
201 response embeds audit.permissions_preview, satisfying "권한 Preview".

Installing a skill whose name already exists in the DB is treated as an
update, not a separate flow (per the brief) -- install_or_update_version()
adds a new SkillVersion and repoints Skill.current_version; nothing here
ever deletes an old SkillVersion row, which is what makes rollback
possible.

Shares the live skills/ directory with skills.py/skills_service.py (via
skills_service.SKILLS_DIR) but does not import anything else from those
modules and does not modify them -- skills_service.py already exposes a
public reset_cache() for exactly this "another module changed skills/
on disk" case, so that's all this module calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from personal_ai.skills.audit import audit_skill
from personal_ai.skills.loader import load_manifest
from personal_ai.skills.store import (
    PathTraversalError,
    SourceNotADirectoryError,
    activate_skill_version,
    install_skill_files,
)
from personal_ai_api import skills_service
from personal_ai_api.skill_store_repository import (
    SkillRecord,
    SkillStoreNotFound,
    SkillStoreRepository,
    SkillVersionRecord,
    get_skill_store_repository,
)

router = APIRouter(prefix="/api/v1", tags=["skill-store"])

LIVE_SKILLS_DIR = skills_service.SKILLS_DIR


class InstallRequest(BaseModel):
    source_path: str


class RollbackRequest(BaseModel):
    version: str


class SkillOut(BaseModel):
    id: str
    name: str
    display_name: str
    description: str | None = None
    current_version: str
    status: str
    installed_at: str
    updated_at: str


class SkillVersionSummaryOut(BaseModel):
    version: str
    created_at: str
    file_hash: str
    audit_passed: bool | None = None
    audit_findings_count: int = 0


def _skill_out(record: SkillRecord) -> SkillOut:
    return SkillOut(**vars(record))


def _version_summary_out(record: SkillVersionRecord) -> SkillVersionSummaryOut:
    audit_report = record.audit_report or {}
    return SkillVersionSummaryOut(
        version=record.version,
        created_at=record.created_at,
        file_hash=record.file_hash,
        audit_passed=audit_report.get("passed"),
        audit_findings_count=len(audit_report.get("findings") or []),
    )


@router.post("/skills/install")
async def install_skill_endpoint(
    payload: InstallRequest,
    repository: SkillStoreRepository = Depends(get_skill_store_repository),
) -> JSONResponse:
    source_dir = Path(payload.source_path)

    try:
        manifest = load_manifest(source_dir / "manifest.yaml")
    except Exception as exc:  # noqa: BLE001 - any manifest failure is a 422, not a 500
        raise HTTPException(status_code=422, detail=f"invalid manifest: {exc}") from exc

    name = manifest.metadata.name
    version = manifest.metadata.version

    audit = audit_skill(source_dir)
    if not audit.passed:
        # SPEC §25 DoD "악성 Skill 차단": rejected here, before anything is
        # copied anywhere -- install_skill_files/activate_skill_version are
        # never called on this path.
        return JSONResponse(
            status_code=422,
            content={"detail": "skill blocked by security audit", "audit": audit.model_dump()},
        )

    try:
        store_path = install_skill_files(name, version, source_dir)
    except (SourceNotADirectoryError, PathTraversalError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    activate_skill_version(name, store_path, LIVE_SKILLS_DIR)

    skill_record, _version_record = await repository.install_or_update_version(
        name=name,
        display_name=manifest.metadata.display_name,
        description=manifest.metadata.description,
        version=version,
        manifest_snapshot=manifest.model_dump(),
        audit_report=audit.model_dump(),
        file_hash=audit.file_hash,
        store_path=str(store_path),
    )

    skills_service.reset_cache()

    return JSONResponse(
        status_code=201,
        content={"skill": _skill_out(skill_record).model_dump(), "audit": audit.model_dump()},
    )


@router.get("/skills/{name}/versions")
async def list_skill_versions_endpoint(
    name: str,
    repository: SkillStoreRepository = Depends(get_skill_store_repository),
) -> list[SkillVersionSummaryOut]:
    try:
        versions = await repository.list_versions(name)
    except SkillStoreNotFound as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    return [_version_summary_out(v) for v in versions]


@router.post("/skills/{name}/rollback")
async def rollback_skill_endpoint(
    name: str,
    payload: RollbackRequest,
    repository: SkillStoreRepository = Depends(get_skill_store_repository),
) -> dict:
    try:
        version_record = await repository.get_version(name, payload.version)
    except SkillStoreNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"version '{payload.version}' not found for skill '{name}'"
        ) from exc

    activate_skill_version(name, Path(version_record.store_path), LIVE_SKILLS_DIR)
    skill_record = await repository.set_current_version(name, payload.version)
    skills_service.reset_cache()

    return {"skill": _skill_out(skill_record).model_dump()}


@router.delete("/skills/{name}/store", status_code=204)
async def remove_skill_endpoint(
    name: str,
    repository: SkillStoreRepository = Depends(get_skill_store_repository),
) -> Response:
    existing = await repository.get_skill_by_name(name)
    if existing is None or existing.status == "removed":
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found")

    live_dir = LIVE_SKILLS_DIR / name
    if live_dir.exists():
        shutil.rmtree(live_dir)

    # SkillVersion history is intentionally left alone -- only Skill.status
    # changes, so a later re-install/rollback can still find past versions.
    await repository.mark_removed(name)
    skills_service.reset_cache()

    return Response(status_code=204)
