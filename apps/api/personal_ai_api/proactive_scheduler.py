"""Background proactive-assistant scheduler (SPEC.md §13: Observe →
Deduplicate → Prioritize → Summarize → Suggest, §25 DoD).

run_check_cycle() is read/record-only: it calls the read-only EventSources,
then only ever *writes Notification rows* -- it never calls a Tool, Skill,
or any other action (SPEC DoD "자동 변경 없음"). The dedup ("반복 알림
제한") and suggest-worthiness ("중요 이벤트만 제안") rules are pulled out
into `_select_new_notifications`, a pure function with no I/O, so those
rules are unit-testable without a database.

run_scheduler_loop() is the background asyncio loop main.py's lifespan
starts on startup and cancels on shutdown; it enforces a hard floor on the
poll interval (SPEC "높은 빈도의 무제한 Polling 금지") and records each run
on the single ScheduledJob row.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from personal_ai.models.db import Notification, ScheduledJob
from personal_ai.proactive.pipeline import compute_dedupe_key, should_suggest, summarize
from personal_ai.proactive.sources import (
    DiskUsageSource,
    DockerHealthSource,
    EventSource,
    GithubCIFailureSource,
    RawEvent,
)
from personal_ai_api.db import async_session_factory, get_default_user_id
from personal_ai_api.proactive.task_deadline_source import TaskDeadlineSource

logger = logging.getLogger(__name__)

JOB_TYPE = "proactive_check"
MIN_CHECK_INTERVAL_SECONDS = 60
DEFAULT_CHECK_INTERVAL_SECONDS = 300
DEDUPE_WINDOW = timedelta(hours=24)


def check_interval_seconds() -> int:
    raw = os.environ.get("PROACTIVE_CHECK_INTERVAL_SECONDS")
    try:
        interval = int(raw) if raw else DEFAULT_CHECK_INTERVAL_SECONDS
    except ValueError:
        interval = DEFAULT_CHECK_INTERVAL_SECONDS
    # SPEC §13 "높은 빈도의 무제한 Polling 금지": a hard floor regardless of
    # what the env var says.
    return max(interval, MIN_CHECK_INTERVAL_SECONDS)


def _quiet_hour(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def quiet_hours() -> tuple[int | None, int | None]:
    return _quiet_hour("QUIET_HOURS_START"), _quiet_hour("QUIET_HOURS_END")


def _build_sources(user_id: str) -> list[EventSource]:
    return [
        GithubCIFailureSource(),
        DiskUsageSource(),
        DockerHealthSource(),
        TaskDeadlineSource(user_id),
    ]


async def _collect_events(user_id: str) -> list[RawEvent]:
    events: list[RawEvent] = []
    for source in _build_sources(user_id):
        try:
            events.extend(await source.check())
        except Exception:  # noqa: BLE001 - one dead source must not block the rest
            logger.warning(
                "proactive source %s failed", getattr(source, "name", source), exc_info=True
            )
    return events


def _select_new_notifications(
    events: list[RawEvent],
    user_id: str,
    existing_dedupe_keys: set[str],
    now: datetime,
    quiet_start: int | None,
    quiet_end: int | None,
) -> list[tuple[RawEvent, str]]:
    """Pure SPEC §13 filter: dedup ("반복 알림 제한") then suggest-worthiness
    ("중요 이벤트만 제안"). Returns (event, dedupe_key) pairs that should
    become new Notification rows."""
    survivors: list[tuple[RawEvent, str]] = []
    for event in events:
        dedupe_key = compute_dedupe_key(user_id, event.source_type, event.external_id)
        if dedupe_key in existing_dedupe_keys:
            continue
        if not should_suggest(event, now, quiet_start, quiet_end):
            continue
        survivors.append((event, dedupe_key))
    return survivors


async def run_check_cycle(
    user_id: str, session_factory: async_sessionmaker = async_session_factory
) -> list[Notification]:
    now = datetime.now(UTC).replace(tzinfo=None)
    quiet_start, quiet_end = quiet_hours()
    events = await _collect_events(user_id)

    async with session_factory() as session:
        existing = await session.execute(
            select(Notification.dedupe_key).where(
                Notification.user_id == uuid.UUID(user_id),
                Notification.created_at >= now - DEDUPE_WINDOW,
            )
        )
        existing_dedupe_keys = set(existing.scalars().all())

        survivors = _select_new_notifications(
            events, user_id, existing_dedupe_keys, now, quiet_start, quiet_end
        )

        created: list[Notification] = []
        for event, dedupe_key in survivors:
            notification = Notification(
                user_id=uuid.UUID(user_id),
                source_type=event.source_type,
                title=event.title,
                body=summarize(event),
                priority=event.severity,
                dedupe_key=dedupe_key,
                status="unseen",
            )
            session.add(notification)
            created.append(notification)

        if created:
            await session.commit()
            for notification in created:
                await session.refresh(notification)

    return created


async def _record_job_run(
    interval_seconds: int, session_factory: async_sessionmaker = async_session_factory
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    async with session_factory() as session:
        result = await session.execute(
            select(ScheduledJob).where(ScheduledJob.job_type == JOB_TYPE)
        )
        job = result.scalar_one_or_none()
        next_run_at = now + timedelta(seconds=interval_seconds)
        if job is None:
            session.add(
                ScheduledJob(
                    job_type=JOB_TYPE,
                    interval_seconds=interval_seconds,
                    last_run_at=now,
                    next_run_at=next_run_at,
                )
            )
        else:
            job.interval_seconds = interval_seconds
            job.last_run_at = now
            job.next_run_at = next_run_at
        await session.commit()


async def run_scheduler_loop() -> None:
    """The background task main.py's lifespan starts/cancels. Runs a check
    cycle immediately, then every check_interval_seconds() thereafter."""
    while True:
        interval = check_interval_seconds()
        try:
            user_id = await get_default_user_id()
            await run_check_cycle(user_id)
        except Exception:  # noqa: BLE001 - the loop itself must never die
            logger.exception("proactive check cycle failed")
        else:
            try:
                await _record_job_run(interval)
            except Exception:  # noqa: BLE001
                logger.exception("failed to record ScheduledJob run")
        await asyncio.sleep(interval)
