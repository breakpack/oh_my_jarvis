"""Approval objects and hash-based tamper detection (SPEC.md §12.2 승인
객체, §12.3 승인 불변 조건). Pure logic, no DB/HTTP: apps/api persists the
ApprovalRequest plus the arguments hash returned alongside it, then calls
verify_arguments_unchanged right before executing an approved action.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

DEFAULT_EXPIRES_IN_SECONDS = 86400


def compute_arguments_hash(arguments: dict) -> str:
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ApprovalRequest(BaseModel):
    id: str
    agent_run_id: str
    action: str
    target: str
    risk_level: str
    arguments: dict
    preview: str
    expected_effects: list[str]
    rollback_available: bool
    expires_at: str | None


def build_approval_request(
    action: str,
    target: str,
    risk_level: str,
    arguments: dict,
    preview: str,
    expected_effects: list[str],
    rollback_available: bool,
    expires_in_seconds: int = DEFAULT_EXPIRES_IN_SECONDS,
) -> tuple[ApprovalRequest, str]:
    expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in_seconds)).isoformat()
    request = ApprovalRequest(
        id=str(uuid.uuid4()),
        agent_run_id=str(uuid.uuid4()),
        action=action,
        target=target,
        risk_level=risk_level,
        arguments=arguments,
        preview=preview,
        expected_effects=expected_effects,
        rollback_available=rollback_available,
        expires_at=expires_at,
    )
    return request, compute_arguments_hash(arguments)


def verify_arguments_unchanged(stored_arguments: dict, stored_hash: str) -> bool:
    return compute_arguments_hash(stored_arguments) == stored_hash
