"""Tests for the Notifications API and the proactive check-cycle rules
(SPEC.md §13, §15, §25 DoD "중요 이벤트만 제안", "자동 변경 없음", "반복
알림 제한").

The dedup + quiet-hours filtering is pulled out into
proactive_scheduler._select_new_notifications, a pure function -- tested
directly here with plain RawEvents, no DB. The router's list/seen/dismiss
endpoints are tested against an in-memory fake NotificationsRepository
(same dependency_overrides pattern as every other apps/api router test).
POST /notifications/check-now is tested by monkeypatching
notifications.run_check_cycle itself (matching test_workflows.py's
approach for a similarly un-mockable-by-DI async function), so no event
source or real DB is ever touched. _collect_events' per-source isolation
is tested by monkeypatching proactive_scheduler._build_sources with a mix
of a raising and a working fake source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import personal_ai_api.notifications as notifications_module
import personal_ai_api.proactive_scheduler as scheduler_module
import pytest
from fastapi.testclient import TestClient
from personal_ai_api.main import app
from personal_ai_api.notifications_repository import (
    NotificationNotFound,
    NotificationRecord,
    get_notifications_repository,
)
from personal_ai_api.proactive_scheduler import _select_new_notifications

from personal_ai.proactive.sources import RawEvent

NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pure dedup / quiet-hours filter logic
# ---------------------------------------------------------------------------


def _event(**overrides) -> RawEvent:
    defaults = dict(
        source_type="disk_usage",
        external_id="disk-2026-08-04",
        title="Disk 95%",
        body="root disk is at 95%",
        severity="high",
    )
    defaults.update(overrides)
    return RawEvent(**defaults)


def test_select_new_notifications_skips_events_with_a_recent_dedupe_key() -> None:
    event = _event()
    from personal_ai.proactive.pipeline import compute_dedupe_key

    key = compute_dedupe_key("user-1", event.source_type, event.external_id)

    survivors = _select_new_notifications([event], "user-1", {key}, NOW, None, None)

    assert survivors == []


def test_select_new_notifications_keeps_a_new_high_severity_event() -> None:
    event = _event(severity="high")

    survivors = _select_new_notifications([event], "user-1", set(), NOW, None, None)

    assert len(survivors) == 1
    assert survivors[0][0] is event


def test_select_new_notifications_drops_low_severity_events() -> None:
    event = _event(severity="low")

    survivors = _select_new_notifications([event], "user-1", set(), NOW, None, None)

    assert survivors == []


def test_select_new_notifications_suppresses_medium_severity_during_quiet_hours() -> None:
    event = _event(severity="medium")
    quiet_now = NOW.replace(hour=23)  # inside a 22-08 quiet window

    survivors = _select_new_notifications([event], "user-1", set(), quiet_now, 22, 8)

    assert survivors == []


def test_select_new_notifications_still_surfaces_high_severity_during_quiet_hours() -> None:
    event = _event(severity="high")
    quiet_now = NOW.replace(hour=23)

    survivors = _select_new_notifications([event], "user-1", set(), quiet_now, 22, 8)

    assert len(survivors) == 1


def test_select_new_notifications_computes_a_stable_dedupe_key_per_event() -> None:
    event = _event(source_type="github_ci_failure", external_id="run-42")

    survivors = _select_new_notifications([event], "user-7", set(), NOW, None, None)

    assert survivors[0][1] == "user-7:github_ci_failure:run-42"


# ---------------------------------------------------------------------------
# check_interval_seconds / quiet_hours: env-driven config, pure functions
# ---------------------------------------------------------------------------


def test_check_interval_seconds_defaults_to_300(monkeypatch) -> None:
    monkeypatch.delenv("PROACTIVE_CHECK_INTERVAL_SECONDS", raising=False)

    assert scheduler_module.check_interval_seconds() == 300


def test_check_interval_seconds_enforces_a_60_second_floor(monkeypatch) -> None:
    """SPEC §13 '높은 빈도의 무제한 Polling 금지': even an aggressive env
    var can't push the loop below 60 seconds."""
    monkeypatch.setenv("PROACTIVE_CHECK_INTERVAL_SECONDS", "5")

    assert scheduler_module.check_interval_seconds() == 60


def test_check_interval_seconds_honors_a_valid_larger_value(monkeypatch) -> None:
    monkeypatch.setenv("PROACTIVE_CHECK_INTERVAL_SECONDS", "900")

    assert scheduler_module.check_interval_seconds() == 900


def test_check_interval_seconds_falls_back_to_default_on_garbage_value(monkeypatch) -> None:
    monkeypatch.setenv("PROACTIVE_CHECK_INTERVAL_SECONDS", "not-a-number")

    assert scheduler_module.check_interval_seconds() == 300


def test_quiet_hours_returns_none_none_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("QUIET_HOURS_START", raising=False)
    monkeypatch.delenv("QUIET_HOURS_END", raising=False)

    assert scheduler_module.quiet_hours() == (None, None)


def test_quiet_hours_parses_both_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("QUIET_HOURS_START", "22")
    monkeypatch.setenv("QUIET_HOURS_END", "8")

    assert scheduler_module.quiet_hours() == (22, 8)


# ---------------------------------------------------------------------------
# _collect_events: one dead source must not block the rest
# ---------------------------------------------------------------------------


class _RaisingSource:
    name = "broken_source"

    async def check(self):
        raise RuntimeError("backend unreachable")


class _WorkingSource:
    name = "working_source"

    def __init__(self, events):
        self._events = events

    async def check(self):
        return self._events


async def test_collect_events_survives_one_source_raising(monkeypatch) -> None:
    good_event = _event(source_type="working_source", external_id="1")
    monkeypatch.setattr(
        scheduler_module,
        "_build_sources",
        lambda user_id: [_RaisingSource(), _WorkingSource([good_event])],
    )

    events = await scheduler_module._collect_events("user-1")

    assert events == [good_event]


# ---------------------------------------------------------------------------
# Router: list / seen / dismiss against a fake repository
# ---------------------------------------------------------------------------


class FakeNotificationsRepository:
    def __init__(self) -> None:
        self.notifications: dict[str, NotificationRecord] = {}

    async def get_or_create_default_user(self) -> str:
        return "user-1"

    async def list_notifications(self, user_id, status) -> list[NotificationRecord]:
        results = list(self.notifications.values())
        if status:
            results = [n for n in results if n.status == status]
        return results

    async def update_notification(self, notification_id, user_id, updates) -> NotificationRecord:
        if notification_id not in self.notifications:
            raise NotificationNotFound(notification_id)
        current = self.notifications[notification_id]
        record = NotificationRecord(**{**vars(current), **updates})
        self.notifications[notification_id] = record
        return record


def _seed(repository: FakeNotificationsRepository, **overrides) -> NotificationRecord:
    defaults = dict(
        id=f"notif-{len(repository.notifications) + 1}",
        source_type="disk_usage",
        title="Disk 95%",
        body="root disk is at 95%",
        priority="high",
        status="unseen",
        created_at="2026-08-04T00:00:00",
        updated_at="2026-08-04T00:00:00",
    )
    defaults.update(overrides)
    record = NotificationRecord(**defaults)
    repository.notifications[record.id] = record
    return record


@pytest.fixture
def repository() -> FakeNotificationsRepository:
    return FakeNotificationsRepository()


@pytest.fixture
def client(repository: FakeNotificationsRepository):
    app.dependency_overrides[get_notifications_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_notifications_defaults_to_unseen(client: TestClient, repository) -> None:
    unseen = _seed(repository)
    seen = _seed(repository, status="seen")

    response = client.get("/api/v1/notifications")

    assert response.status_code == 200
    ids = {n["id"] for n in response.json()}
    assert ids == {unseen.id}
    assert seen.id not in ids


def test_list_notifications_can_filter_by_status(client: TestClient, repository) -> None:
    _seed(repository)
    dismissed = _seed(repository, status="dismissed")

    response = client.get("/api/v1/notifications", params={"status": "dismissed"})

    assert response.status_code == 200
    ids = {n["id"] for n in response.json()}
    assert ids == {dismissed.id}


def test_mark_seen_updates_status(client: TestClient, repository) -> None:
    notification = _seed(repository)

    response = client.post(f"/api/v1/notifications/{notification.id}/seen")

    assert response.status_code == 200
    assert response.json()["status"] == "seen"
    assert repository.notifications[notification.id].status == "seen"


def test_dismiss_updates_status(client: TestClient, repository) -> None:
    notification = _seed(repository)

    response = client.post(f"/api/v1/notifications/{notification.id}/dismiss")

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"


def test_mark_seen_unknown_notification_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/notifications/does-not-exist/seen")

    assert response.status_code == 404


def test_dismiss_unknown_notification_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/notifications/does-not-exist/dismiss")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /notifications/check-now
# ---------------------------------------------------------------------------


def test_check_now_returns_newly_created_notifications(client: TestClient, monkeypatch) -> None:
    fake_notification = SimpleNamespace(
        id="notif-new",
        source_type="disk_usage",
        title="Disk 95%",
        body="root disk is at 95%",
        priority="high",
        status="unseen",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    async def fake_run_check_cycle(user_id):
        assert user_id == "user-1"
        return [fake_notification]

    monkeypatch.setattr(notifications_module, "run_check_cycle", fake_run_check_cycle)

    response = client.post("/api/v1/notifications/check-now")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "notif-new"
    assert body[0]["priority"] == "high"


def test_check_now_returns_empty_list_when_nothing_new(client: TestClient, monkeypatch) -> None:
    async def fake_run_check_cycle(user_id):
        return []

    monkeypatch.setattr(notifications_module, "run_check_cycle", fake_run_check_cycle)

    response = client.post("/api/v1/notifications/check-now")

    assert response.status_code == 200
    assert response.json() == []
