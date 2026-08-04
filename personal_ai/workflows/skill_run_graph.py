"""Durable, resumable Skill execution (SPEC.md §5.2, §25 DoD "서버 재시작
후 복구", "승인 대기 유지", "중복 Tool 실행 방지").

This is a second, additional execution path alongside apps/api's existing
POST /skills/{name}/run + POST /approvals/{id}/approve (untouched,
already covered by 100+ tests) — that path is "approve now, simple";
this one is for when a caller genuinely needs a workflow that survives a
server restart while paused on approval. Same Skills, same Policy Engine,
different durability guarantee.

Graph shape: plan -> gate -> [execute -> verify | END] -> END. `gate` is
where `interrupt()` pauses the graph (LangGraph's checkpointer persists
that pause to Postgres — see checkpointer.py) whenever the skill's
risk_level requires approval and none has been supplied yet.
"""

from __future__ import annotations

import importlib.util
import inspect
import uuid
from pathlib import Path
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from personal_ai.models.db import ToolExecution
from personal_ai.security.approval import compute_arguments_hash
from personal_ai.security.policy import RestrictedActionError, requires_approval
from personal_ai.skills.registry import LoadedSkill, SkillRegistry
from personal_ai.skills.sdk import SkillContext, SkillResult
from personal_ai.workflows.checkpointer import get_checkpointer
from personal_ai.workflows.db import get_session_factory

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"


class SkillNotFoundError(Exception):
    pass


class SkillNotImplementedError(Exception):
    pass


class SkillRunState(TypedDict):
    skill_name: str
    arguments: dict
    user_id: str
    plan: list | None
    approval_decision: str | None
    result: dict | None


def _load_skill(skill_name: str) -> LoadedSkill:
    for skill in SkillRegistry().discover(SKILLS_DIR):
        if skill.name == skill_name:
            return skill
    raise SkillNotFoundError(skill_name)


def _find_skill_class(loaded: LoadedSkill) -> type | None:
    """Dynamically import skills/<name>/workflow.py and return the class
    implementing the Skill protocol (plan/execute/verify) it defines, or
    None for a stub skill with no workflow.py yet.

    Same technique as apps/api/personal_ai_api/skills_service.py's
    find_skill_class, reimplemented here rather than imported — this
    module must not depend on the apps/api app layer.
    """
    workflow_path = Path(loaded.path) / "workflow.py"
    if not workflow_path.is_file():
        return None

    module_name = f"personal_ai.workflows._skill_modules.{loaded.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, workflow_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            obj.__module__ == module.__name__
            and hasattr(obj, "plan")
            and hasattr(obj, "execute")
            and hasattr(obj, "verify")
        ):
            return obj
    return None


def _load_skill_and_class(skill_name: str) -> tuple[LoadedSkill, type]:
    loaded = _load_skill(skill_name)
    skill_cls = _find_skill_class(loaded)
    if skill_cls is None:
        raise SkillNotImplementedError(skill_name)
    return loaded, skill_cls


def _build_context(state: SkillRunState, loaded: LoadedSkill) -> SkillContext:
    return SkillContext(
        user_id=state["user_id"],
        conversation_id=str(uuid.uuid4()),
        project_id=None,
        workspace_id=None,
        local_only=False,
        granted_scopes=set(loaded.manifest.permissions.scopes),
    )


async def execute_skill_with_dedup(
    thread_id: str,
    skill_name: str,
    arguments: dict,
    context: SkillContext,
    skill: object,
) -> dict:
    """The "execute" node's actual logic (SPEC §25 DoD "중복 Tool 실행
    방지"), split out so it can also be exercised directly (called twice
    with the same thread_id) without needing a full graph interrupt/resume
    round trip to prove skill.execute() only ever runs once.

    UNIQUE(workflow_thread_id, tool_name, arguments_hash) on
    tool_executions is the actual guarantee: an INSERT racing against an
    already-running-or-completed row fails, and that failure is the signal
    to read the existing row and reuse it instead of executing again.
    """
    arguments_hash = compute_arguments_hash(arguments)
    session_factory = get_session_factory()

    async with session_factory() as session:
        row = (
            await session.execute(
                select(ToolExecution).where(
                    ToolExecution.workflow_thread_id == thread_id,
                    ToolExecution.tool_name == skill_name,
                    ToolExecution.arguments_hash == arguments_hash,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = ToolExecution(
                workflow_thread_id=thread_id,
                tool_name=skill_name,
                arguments_hash=arguments_hash,
                status="running",
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                row = (
                    await session.execute(
                        select(ToolExecution).where(
                            ToolExecution.workflow_thread_id == thread_id,
                            ToolExecution.tool_name == skill_name,
                            ToolExecution.arguments_hash == arguments_hash,
                        )
                    )
                ).scalar_one()

        if row.status == "completed":
            return row.result

        skill_result = await skill.execute(arguments, context)  # type: ignore[attr-defined]
        result_dict = skill_result.model_dump()

        row.status = "completed"
        row.result = result_dict
        session.add(row)
        await session.commit()

    return result_dict


async def _plan_node(state: SkillRunState) -> dict:
    loaded, skill_cls = _load_skill_and_class(state["skill_name"])
    context = _build_context(state, loaded)
    plan = await skill_cls().plan(state["arguments"], context)
    return {"plan": plan}


async def _gate_node(state: SkillRunState) -> dict:
    loaded, _ = _load_skill_and_class(state["skill_name"])
    risk_level = loaded.manifest.permissions.risk_level

    try:
        approval_needed = requires_approval(risk_level)
    except RestrictedActionError as exc:
        failure = SkillResult(success=False, summary="action is restricted", error=str(exc))
        return {"approval_decision": "reject", "result": failure.model_dump()}

    if not approval_needed:
        return {"approval_decision": "approve"}

    decision = state.get("approval_decision")
    if decision is None:
        # Pauses the graph here; the checkpointer persists this exact
        # point to Postgres. On resume, `interrupt()` returns the value
        # passed to Command(resume=...) instead of pausing again.
        decision = interrupt(
            {
                "reason": "approval_required",
                "skill": state["skill_name"],
                "arguments": state["arguments"],
                "preview": state.get("plan"),
            }
        )

    if decision == "reject":
        failure = SkillResult(
            success=False, summary="rejected by approver", error="approval rejected"
        )
        return {"approval_decision": decision, "result": failure.model_dump()}

    return {"approval_decision": decision}


def _after_gate(state: SkillRunState) -> str:
    return END if state.get("result") is not None else "execute"


async def _execute_node(state: SkillRunState, config: RunnableConfig) -> dict:
    if state.get("result") is not None:
        return {}

    loaded, skill_cls = _load_skill_and_class(state["skill_name"])
    context = _build_context(state, loaded)
    thread_id = config["configurable"]["thread_id"]

    result_dict = await execute_skill_with_dedup(
        thread_id, state["skill_name"], state["arguments"], context, skill_cls()
    )
    return {"result": result_dict}


async def _verify_node(state: SkillRunState) -> dict:
    result = state.get("result")
    if result is None:
        return {}
    loaded, skill_cls = _load_skill_and_class(state["skill_name"])
    context = _build_context(state, loaded)
    verified = await skill_cls().verify(SkillResult(**result), context)
    return {"result": verified.model_dump()}


def _build_graph(checkpointer: BaseCheckpointSaver):
    graph = StateGraph(SkillRunState)
    graph.add_node("plan", _plan_node)
    graph.add_node("gate", _gate_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("verify", _verify_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "gate")
    graph.add_conditional_edges("gate", _after_gate, {"execute": "execute", END: END})
    graph.add_edge("execute", "verify")
    graph.add_edge("verify", END)
    return graph.compile(checkpointer=checkpointer)


def _to_response(result: dict, thread_id: str) -> dict:
    if "__interrupt__" in result:
        interrupts = result["__interrupt__"]
        payload = interrupts[0].value if interrupts else None
        return {"status": "pending_approval", "thread_id": thread_id, "interrupt": payload}
    return {"status": "completed", "thread_id": thread_id, "result": result.get("result")}


async def run_skill_workflow(
    skill_name: str, arguments: dict, user_id: str, thread_id: str | None = None
) -> dict:
    thread_id = thread_id or str(uuid.uuid4())
    checkpointer = await get_checkpointer()
    app = _build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: SkillRunState = {
        "skill_name": skill_name,
        "arguments": arguments,
        "user_id": user_id,
        "plan": None,
        "approval_decision": None,
        "result": None,
    }
    result = await app.ainvoke(initial_state, config=config)
    return _to_response(result, thread_id)


async def resume_skill_workflow(thread_id: str, decision: str) -> dict:
    """Resume a paused workflow using only Postgres-persisted checkpoint
    state — get_checkpointer() and _build_graph() here construct a
    brand-new saver/app, exactly as a freshly restarted process would."""
    checkpointer = await get_checkpointer()
    app = _build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    result = await app.ainvoke(Command(resume=decision), config=config)
    return _to_response(result, thread_id)
