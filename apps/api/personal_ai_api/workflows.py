"""Durable Skill workflow API (SPEC.md §5.2, §15, §25 DoD "서버 재시작 후
복구", "승인 대기 유지", "중복 Tool 실행 방지").

A second, parallel path alongside POST /skills/{name}/run + POST
/approvals/{id}/approve (apps/api/personal_ai_api/skills.py + approvals.py,
untouched by this phase) -- that path is "approve now, in-memory simple";
this one durably persists pause-on-approval state to Postgres via
LangGraph's checkpointer (personal_ai.workflows.skill_run_graph), so a
paused workflow survives a server restart.

No GET /workflows/{thread_id} status endpoint in this phase: the
checkpointer's on-disk format is LangGraph-internal, not a stable API
contract, and resume's own response already reports the current status
(pending_approval or completed) -- a dedicated read-only status layer is
deferred until something actually needs to poll a thread it didn't just
run/resume itself.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from personal_ai.workflows.skill_run_graph import (
    SkillNotFoundError,
    SkillNotImplementedError,
    resume_skill_workflow,
    run_skill_workflow,
)
from personal_ai_api.db import get_default_user_id

router = APIRouter(prefix="/api/v1", tags=["workflows"])


class WorkflowRunRequest(BaseModel):
    arguments: dict = {}


class WorkflowResumeRequest(BaseModel):
    # A non-approve/reject decision fails FastAPI's request validation with
    # 422 automatically -- exactly the "decision이 approve/reject가 아니면
    # 422" requirement, with no manual check needed.
    decision: Literal["approve", "reject"]


def _respond(result: dict) -> JSONResponse:
    status_code = 202 if result.get("status") == "pending_approval" else 200
    return JSONResponse(status_code=status_code, content=result)


@router.post("/workflows/skills/{name}/run")
async def run_workflow_endpoint(
    name: str,
    payload: WorkflowRunRequest,
    user_id: str = Depends(get_default_user_id),
) -> JSONResponse:
    try:
        result = await run_skill_workflow(name, payload.arguments, user_id)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"skill '{name}' not found") from exc
    except SkillNotImplementedError as exc:
        raise HTTPException(
            status_code=501, detail=f"skill '{name}' is not yet implemented (stub only)"
        ) from exc
    return _respond(result)


@router.post("/workflows/{thread_id}/resume")
async def resume_workflow_endpoint(thread_id: str, payload: WorkflowResumeRequest) -> JSONResponse:
    try:
        result = await resume_skill_workflow(thread_id, payload.decision)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workflow not found") from exc
    except SkillNotImplementedError as exc:
        raise HTTPException(
            status_code=501, detail="skill is not yet implemented (stub only)"
        ) from exc
    return _respond(result)
