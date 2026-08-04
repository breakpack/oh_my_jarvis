"""Notifications API (SPEC.md §13 능동적 개인비서, §15, §25 DoD)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from personal_ai_api.notifications_repository import (
    NotificationNotFound,
    NotificationRecord,
    NotificationsRepository,
    get_notifications_repository,
)
from personal_ai_api.proactive_scheduler import run_check_cycle

router = APIRouter(prefix="/api/v1", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    source_type: str
    title: str
    body: str
    priority: str
    status: str
    created_at: str
    updated_at: str


def _to_out(record: NotificationRecord) -> NotificationOut:
    return NotificationOut(**vars(record))


def _orm_to_out(notification) -> NotificationOut:
    """run_check_cycle() returns real Notification ORM rows, not Records
    (see notifications_repository.py's module docstring) -- this converts
    those, reading .isoformat() off real datetimes rather than a
    pre-stringified dataclass field."""
    return NotificationOut(
        id=str(notification.id),
        source_type=notification.source_type,
        title=notification.title,
        body=notification.body,
        priority=notification.priority,
        status=notification.status,
        created_at=notification.created_at.isoformat(),
        updated_at=notification.updated_at.isoformat(),
    )


@router.get("/notifications")
async def list_notifications_endpoint(
    status: str | None = "unseen",
    repository: NotificationsRepository = Depends(get_notifications_repository),
) -> list[NotificationOut]:
    user_id = await repository.get_or_create_default_user()
    notifications = await repository.list_notifications(user_id, status)
    return [_to_out(n) for n in notifications]


@router.post("/notifications/{notification_id}/seen")
async def mark_notification_seen_endpoint(
    notification_id: str,
    repository: NotificationsRepository = Depends(get_notifications_repository),
) -> NotificationOut:
    user_id = await repository.get_or_create_default_user()
    try:
        notification = await repository.update_notification(
            notification_id, user_id, {"status": "seen"}
        )
    except NotificationNotFound as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc
    return _to_out(notification)


@router.post("/notifications/{notification_id}/dismiss")
async def dismiss_notification_endpoint(
    notification_id: str,
    repository: NotificationsRepository = Depends(get_notifications_repository),
) -> NotificationOut:
    user_id = await repository.get_or_create_default_user()
    try:
        notification = await repository.update_notification(
            notification_id, user_id, {"status": "dismissed"}
        )
    except NotificationNotFound as exc:
        raise HTTPException(status_code=404, detail="Notification not found") from exc
    return _to_out(notification)


@router.post("/notifications/check-now")
async def check_now_endpoint(
    repository: NotificationsRepository = Depends(get_notifications_repository),
) -> list[NotificationOut]:
    """Manual/demo/test trigger: runs one check cycle synchronously (the
    same run_check_cycle the background scheduler calls) and returns
    whatever new Notifications it just created."""
    user_id = await repository.get_or_create_default_user()
    notifications = await run_check_cycle(user_id)
    return [_orm_to_out(n) for n in notifications]
