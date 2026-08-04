"""Skill SDK (SPEC.md §6.4 manifest.yaml, §6.7 Skill SDK).

SkillManifest models manifest.yaml field-for-field. A malformed manifest
(missing field, wrong type) fails to construct with a pydantic
ValidationError — that's the whole mechanism behind SPEC §6.9's "잘못된
Manifest 차단" (reject a bad manifest before install/run), so no manual
validation logic lives here on top of pydantic's own.

Only `approval`, `verification`, and `rollback` are optional sections
(SPEC §6.4 shows every manifest example with them present, but SPEC §6.2
allows a minimal skill with just SKILL.md + manifest.yaml, so these three
— which only matter once a skill performs risky/verified/undoable actions
— default to absent).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class SkillMetadata(BaseModel):
    name: str
    display_name: str
    version: str
    description: str
    license: str
    author: str
    tags: list[str]


class SkillRuntime(BaseModel):
    type: str
    entrypoint: str
    timeout_seconds: int
    network_access: str


class SkillModels(BaseModel):
    preferred: list[str]
    local_only_supported: bool


class SkillCapabilities(BaseModel):
    tools: list[str]
    resources: list[str]


class SkillPermissions(BaseModel):
    risk_level: str
    scopes: list[str]


class SkillApproval(BaseModel):
    required_before: list[str]


class SkillVerification(BaseModel):
    required: bool
    checks: list[str]


class SkillRollback(BaseModel):
    supported: bool
    strategy: str


class SkillManifest(BaseModel):
    api_version: str
    kind: str
    metadata: SkillMetadata
    runtime: SkillRuntime
    models: SkillModels
    capabilities: SkillCapabilities
    permissions: SkillPermissions
    approval: SkillApproval | None = None
    input_schema: str
    output_schema: str
    verification: SkillVerification | None = None
    rollback: SkillRollback | None = None


class SkillContext(BaseModel):
    user_id: str
    conversation_id: str
    project_id: str | None
    workspace_id: str | None
    local_only: bool
    granted_scopes: set[str]


class SkillResult(BaseModel):
    success: bool
    summary: str
    data: dict | None = None
    evidence: list[dict] = []
    artifacts: list[dict] = []
    rollback_token: str | None = None
    error: str | None = None


class Skill(Protocol):
    manifest: dict

    async def plan(
        self,
        arguments: dict,
        context: SkillContext,
    ) -> list[dict]: ...

    async def execute(
        self,
        arguments: dict,
        context: SkillContext,
    ) -> SkillResult: ...

    async def verify(
        self,
        result: SkillResult,
        context: SkillContext,
    ) -> SkillResult: ...

    async def rollback(
        self,
        rollback_token: str,
        context: SkillContext,
    ) -> SkillResult: ...
