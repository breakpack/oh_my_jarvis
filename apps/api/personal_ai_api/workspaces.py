"""Workspaces API (SPEC.md §9 Development Mode, §12 commit approval gate).

POST /workspaces/{id}/commit never runs `git commit` itself -- SPEC §25 DoD
"승인 전 commit 금지": it always creates a pending Approval (medium risk,
same gate shape as skills.py's) and returns 202. The actual `git add` +
`git commit` runs from approvals.py's approve endpoint, once hash-verified
and approved -- GitWorktreeRuntime deliberately has no commit method of its
own (see its module docstring) for exactly this reason.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from personal_ai.development.workspace import (
    WORKSPACE_BASE_DIR,
    DevelopmentRuntime,
    GitWorktreeRuntime,
    WorkspaceNotFound,
)
from personal_ai.security.approval import build_approval_request
from personal_ai_api.approvals_repository import ApprovalsRepository, get_approvals_repository
from personal_ai_api.workspaces_repository import (
    WorkspaceRecord,
    WorkspaceRecordNotFound,
    WorkspacesRepository,
    get_workspaces_repository,
)

router = APIRouter(prefix="/api/v1", tags=["workspaces"])

COMMIT_ACTION_PREFIX = "workspace_commit:"
COMMIT_RISK_LEVEL = "medium"


def get_workspace_runtime() -> DevelopmentRuntime:
    return GitWorktreeRuntime()


class WorkspaceCreate(BaseModel):
    source: str


class WorkspaceOut(BaseModel):
    id: str
    source_path: str
    workspace_dir: str
    status: str
    created_at: str
    updated_at: str


class WorkspaceRunRequest(BaseModel):
    command: list[str]


class WorkspaceRunOut(BaseModel):
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int


class WorkspaceDiffOut(BaseModel):
    diff: str


class WorkspaceSearchRequest(BaseModel):
    query: str


class WorkspaceFileOut(BaseModel):
    content: str


class WorkspacePatchRequest(BaseModel):
    patch: str


class WorkspacePatchOut(BaseModel):
    success: bool
    stderr: str


class WorkspaceCommitRequest(BaseModel):
    message: str


def _to_out(record: WorkspaceRecord) -> WorkspaceOut:
    return WorkspaceOut(**vars(record))


async def _require_workspace(
    workspace_id: str, repository: WorkspacesRepository
) -> tuple[str, WorkspaceRecord]:
    user_id = await repository.get_or_create_default_user()
    try:
        workspace = await repository.get_workspace(workspace_id, user_id)
    except WorkspaceRecordNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    return user_id, workspace


@router.post("/workspaces", status_code=201)
async def create_workspace_endpoint(
    payload: WorkspaceCreate,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> WorkspaceOut:
    user_id = await repository.get_or_create_default_user()
    try:
        workspace_id = await runtime.create_workspace(payload.source)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="repository not in allowed list") from exc

    workspace_dir = str(WORKSPACE_BASE_DIR / workspace_id)
    workspace = await repository.create_workspace(
        user_id, workspace_id, payload.source, workspace_dir
    )
    return _to_out(workspace)


@router.get("/workspaces/{workspace_id}")
async def get_workspace_endpoint(
    workspace_id: str,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
) -> WorkspaceOut:
    _, workspace = await _require_workspace(workspace_id, repository)
    return _to_out(workspace)


@router.post("/workspaces/{workspace_id}/run")
async def run_workspace_command_endpoint(
    workspace_id: str,
    payload: WorkspaceRunRequest,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> WorkspaceRunOut:
    await _require_workspace(workspace_id, repository)
    try:
        result = await runtime.run_command(workspace_id, payload.command)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="command not allowed") from exc
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc

    await repository.record_run(
        workspace_id,
        payload.command,
        result["exit_code"],
        result["stdout"],
        result["stderr"],
        result["duration_ms"],
    )
    return WorkspaceRunOut(**result)


@router.get("/workspaces/{workspace_id}/diff")
async def get_workspace_diff_endpoint(
    workspace_id: str,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> WorkspaceDiffOut:
    await _require_workspace(workspace_id, repository)
    try:
        diff = await runtime.get_diff(workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    return WorkspaceDiffOut(diff=diff)


@router.post("/workspaces/{workspace_id}/search")
async def search_workspace_endpoint(
    workspace_id: str,
    payload: WorkspaceSearchRequest,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> list[dict]:
    await _require_workspace(workspace_id, repository)
    try:
        return await runtime.search(workspace_id, payload.query)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc


@router.get("/workspaces/{workspace_id}/file")
async def read_workspace_file_endpoint(
    workspace_id: str,
    path: str,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> WorkspaceFileOut:
    await _require_workspace(workspace_id, repository)
    try:
        content = await runtime.read_file(workspace_id, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="path escapes workspace repository") from exc
    except (FileNotFoundError, WorkspaceNotFound) as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    return WorkspaceFileOut(content=content)


@router.post("/workspaces/{workspace_id}/apply-patch")
async def apply_patch_endpoint(
    workspace_id: str,
    payload: WorkspacePatchRequest,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> WorkspacePatchOut:
    await _require_workspace(workspace_id, repository)
    try:
        result = await runtime.apply_patch(workspace_id, payload.patch)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=404, detail="Workspace not found") from exc
    return WorkspacePatchOut(**result)


@router.post("/workspaces/{workspace_id}/commit")
async def commit_workspace_endpoint(
    workspace_id: str,
    payload: WorkspaceCommitRequest,
    response: Response,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    approvals_repository: ApprovalsRepository = Depends(get_approvals_repository),
) -> dict:
    user_id, _workspace = await _require_workspace(workspace_id, repository)

    # SPEC §25 DoD "승인 전 commit 금지": git add/commit must never run on
    # this path -- only approvals.py's approve endpoint runs them, and only
    # after re-verifying the arguments hash.
    arguments = {"workspace_id": workspace_id, "message": payload.message}
    approval_request, arguments_hash = build_approval_request(
        action=f"{COMMIT_ACTION_PREFIX}{workspace_id}",
        target=workspace_id,
        risk_level=COMMIT_RISK_LEVEL,
        arguments=arguments,
        preview=f"git commit -m '{payload.message}' in workspace {workspace_id}",
        expected_effects=["Creates a local git commit in the workspace worktree"],
        rollback_available=False,
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


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def destroy_workspace_endpoint(
    workspace_id: str,
    repository: WorkspacesRepository = Depends(get_workspaces_repository),
    runtime: DevelopmentRuntime = Depends(get_workspace_runtime),
) -> Response:
    user_id, _workspace = await _require_workspace(workspace_id, repository)
    await runtime.destroy_workspace(workspace_id)
    await repository.update_workspace(workspace_id, user_id, {"status": "destroyed"})
    return Response(status_code=204)
