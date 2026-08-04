"""Pure pipeline logic for the proactive assistant (SPEC.md §13:
Observe → Deduplicate → Prioritize → Summarize → Suggest, and its "금지"
list — no unnecessary repeat notifications, no unapproved external
changes here at all).

No DB, no I/O: dedup-key computation, the quiet-hours/priority decision,
and event summarization are all pure functions, independent of whatever
storage layer ends up calling them.
"""

from __future__ import annotations

from datetime import datetime

from personal_ai.proactive.sources import RawEvent

_SUGGESTIBLE_SEVERITIES = {"medium", "high"}


def compute_dedupe_key(user_id: str, source_type: str, external_id: str) -> str:
    return f"{user_id}:{source_type}:{external_id}"


def is_quiet_hours(now: datetime, start_hour: int, end_hour: int) -> bool:
    hour = now.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    # start_hour >= end_hour: wraps past midnight (e.g. 22 -> 8). Treating
    # start_hour == end_hour the same way makes it an "all day" window,
    # which is the standard reading of a zero-width wraparound range.
    return hour >= start_hour or hour < end_hour


def should_suggest(
    event: RawEvent, now: datetime, quiet_start: int | None, quiet_end: int | None
) -> bool:
    """Whether this event is worth surfacing as a proactive suggestion —
    not whether it gets recorded at all (SPEC §13 "중요 이벤트만 제안":
    the caller may still store every observed event; this only gates the
    interruption)."""
    if event.severity not in _SUGGESTIBLE_SEVERITIES:
        return False  # "low", or any unrecognized value — fail closed.

    if quiet_start is None or quiet_end is None:
        return True

    if is_quiet_hours(now, quiet_start, quiet_end):
        return event.severity == "high"
    return True


_SUMMARY_TEMPLATES = {
    "github_ci_failure": "GitHub CI 실패가 감지되었습니다: {title}. {body}",
    "disk_usage": "디스크 공간이 부족합니다 — {title}. {body}",
    "docker_health": "Docker 컨테이너에 문제가 발생했습니다: {title}. {body}",
}


def summarize(event: RawEvent) -> str:
    template = _SUMMARY_TEMPLATES.get(event.source_type, "{title}. {body}")
    return template.format(title=event.title, body=event.body)
