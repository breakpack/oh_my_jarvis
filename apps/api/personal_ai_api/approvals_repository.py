"""Persistence for the Approvals API (SPEC.md §12 Policy/Approval,
§20.4 Audit)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Approval, AuditEvent
from personal_ai_api.db import async_session_factory
from personal_ai_api.db import get_or_create_default_user as _get_or_create_default_user


@dataclass
class ApprovalRecord:
    id: str
    action: str
    target: str
    risk_level: str
    arguments: dict
    arguments_hash: str
    preview: str
    expected_effects: list
    rollback_available: bool
    rollback_token: str | None
    status: str
    expires_at: str | None
    created_at: str
    updated_at: str


class ApprovalNotFound(Exception):
    pass


class ApprovalsRepository(Protocol):
    async def get_or_create_default_user(self) -> str: ...

    async def create_approval(
        self,
        user_id: str,
        action: str,
        target: str,
        risk_level: str,
        arguments: dict,
        arguments_hash: str,
        preview: str,
        expected_effects: list[str],
        rollback_available: bool,
        expires_at: datetime | None,
    ) -> ApprovalRecord: ...

    async def list_approvals(
        self, user_id: str, status: str | None = "pending"
    ) -> list[ApprovalRecord]: ...

    async def get_approval(self, approval_id: str, user_id: str) -> ApprovalRecord: ...

    async def update_approval(
        self, approval_id: str, user_id: str, updates: dict
    ) -> ApprovalRecord: ...

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None: ...


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApprovalNotFound(value) from exc


class SqlAlchemyApprovalsRepository:
    def __init__(self, session_factory: async_sessionmaker = async_session_factory) -> None:
        self._session_factory = session_factory

    async def get_or_create_default_user(self) -> str:
        return await _get_or_create_default_user(self._session_factory)

    async def create_approval(
        self,
        user_id: str,
        action: str,
        target: str,
        risk_level: str,
        arguments: dict,
        arguments_hash: str,
        preview: str,
        expected_effects: list[str],
        rollback_available: bool,
        expires_at: datetime | None,
    ) -> ApprovalRecord:
        async with self._session_factory() as session:
            approval = Approval(
                user_id=_parse_uuid(user_id),
                action=action,
                target=target,
                risk_level=risk_level,
                arguments=arguments,
                arguments_hash=arguments_hash,
                preview=preview,
                expected_effects=expected_effects,
                rollback_available=rollback_available,
                expires_at=expires_at,
            )
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            return _to_record(approval)

    async def list_approvals(
        self, user_id: str, status: str | None = "pending"
    ) -> list[ApprovalRecord]:
        async with self._session_factory() as session:
            stmt = select(Approval).where(Approval.user_id == _parse_uuid(user_id))
            if status:
                stmt = stmt.where(Approval.status == status)
            result = await session.execute(stmt.order_by(Approval.created_at.desc()))
            return [_to_record(a) for a in result.scalars().all()]

    async def get_approval(self, approval_id: str, user_id: str) -> ApprovalRecord:
        async with self._session_factory() as session:
            approval = await self._get_owned(session, approval_id, user_id)
            return _to_record(approval)

    async def update_approval(
        self, approval_id: str, user_id: str, updates: dict
    ) -> ApprovalRecord:
        async with self._session_factory() as session:
            approval = await self._get_owned(session, approval_id, user_id)
            for field, value in updates.items():
                setattr(approval, field, value)
            await session.commit()
            await session.refresh(approval)
            return _to_record(approval)

    async def record_audit(self, user_id: str, event_type: str, payload: dict) -> None:
        async with self._session_factory() as session:
            session.add(
                AuditEvent(user_id=_parse_uuid(user_id), event_type=event_type, payload=payload)
            )
            await session.commit()

    async def _get_owned(self, session, approval_id: str, user_id: str) -> Approval:
        result = await session.execute(
            select(Approval).where(
                Approval.id == _parse_uuid(approval_id), Approval.user_id == _parse_uuid(user_id)
            )
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalNotFound(approval_id)
        return approval


def _to_record(approval: Approval) -> ApprovalRecord:
    return ApprovalRecord(
        id=str(approval.id),
        action=approval.action,
        target=approval.target,
        risk_level=approval.risk_level,
        arguments=approval.arguments,
        arguments_hash=approval.arguments_hash,
        preview=approval.preview,
        expected_effects=approval.expected_effects,
        rollback_available=approval.rollback_available,
        rollback_token=approval.rollback_token,
        status=approval.status,
        expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
        created_at=approval.created_at.isoformat(),
        updated_at=approval.updated_at.isoformat(),
    )


def get_approvals_repository() -> ApprovalsRepository:
    return SqlAlchemyApprovalsRepository()
