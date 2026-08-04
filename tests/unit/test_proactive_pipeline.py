"""Unit tests for personal_ai.proactive.pipeline (SPEC.md §13). Pure
functions, no mocking needed.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from personal_ai.proactive.pipeline import (
    compute_dedupe_key,
    is_quiet_hours,
    should_suggest,
    summarize,
)
from personal_ai.proactive.sources import RawEvent


def _at(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, 0, 0)


# --- is_quiet_hours ----------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (8, False),
        (9, True),
        (12, True),
        (16, True),
        (17, False),
        (0, False),
        (23, False),
    ],
)
def test_is_quiet_hours_normal_same_day_range(hour, expected):
    assert is_quiet_hours(_at(hour), 9, 17) is expected


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (21, False),  # before quiet hours start
        (22, True),  # exactly at start
        (23, True),
        (0, True),  # past midnight
        (7, True),
        (8, False),  # exactly at end — end is exclusive
        (9, False),
    ],
)
def test_is_quiet_hours_wraps_past_midnight(hour, expected):
    assert is_quiet_hours(_at(hour), 22, 8) is expected


def test_is_quiet_hours_equal_start_and_end_is_treated_as_all_day():
    for hour in (0, 6, 12, 18, 23):
        assert is_quiet_hours(_at(hour), 5, 5) is True


# --- should_suggest ------------------------------------------------------


def _event(severity: str) -> RawEvent:
    return RawEvent(
        source_type="disk_usage", external_id="x", title="t", body="b", severity=severity
    )


def test_should_suggest_low_severity_is_always_false():
    # Even with no quiet hours configured at all.
    assert should_suggest(_event("low"), _at(12), None, None) is False
    assert should_suggest(_event("low"), _at(3), 22, 8) is False


def test_should_suggest_unrecognized_severity_fails_closed():
    assert should_suggest(_event("unknown"), _at(12), None, None) is False


@pytest.mark.parametrize("severity", ["medium", "high"])
def test_should_suggest_no_quiet_hours_configured_allows_medium_and_high(severity):
    assert should_suggest(_event(severity), _at(3), None, None) is True


def test_should_suggest_outside_quiet_hours_allows_medium_and_high():
    # Quiet hours 22-8; 12:00 is outside that window.
    assert should_suggest(_event("medium"), _at(12), 22, 8) is True
    assert should_suggest(_event("high"), _at(12), 22, 8) is True


def test_should_suggest_inside_quiet_hours_only_allows_high():
    # Quiet hours 22-8; 3:00 is inside that window.
    assert should_suggest(_event("medium"), _at(3), 22, 8) is False
    assert should_suggest(_event("high"), _at(3), 22, 8) is True


def test_should_suggest_only_one_of_quiet_start_end_set_is_treated_as_unconfigured():
    assert should_suggest(_event("medium"), _at(3), 22, None) is True
    assert should_suggest(_event("medium"), _at(3), None, 8) is True


# --- summarize -------------------------------------------------------------


def test_summarize_produces_distinct_text_per_source_type():
    events = [
        RawEvent(
            source_type="github_ci_failure",
            external_id="1",
            title="CI 실패: build",
            body="owner/repo: https://example.com",
            severity="medium",
        ),
        RawEvent(
            source_type="disk_usage",
            external_id="2",
            title="디스크 사용률 96.0%",
            body="루트 디스크(/)가 96.0% 사용 중입니다.",
            severity="high",
        ),
        RawEvent(
            source_type="docker_health",
            external_id="3",
            title="컨테이너 이상: my-app",
            body="my-image — 상태: Exited (1) 2 minutes ago",
            severity="high",
        ),
    ]

    summaries = [summarize(e) for e in events]

    assert len(set(summaries)) == len(summaries)  # all different
    assert "GitHub CI" in summaries[0]
    assert "디스크" in summaries[1]
    assert "Docker" in summaries[2]
    # Every summary still carries the event's own title/body through.
    for event, summary in zip(events, summaries, strict=True):
        assert event.title in summary
        assert event.body in summary


def test_summarize_falls_back_to_a_generic_template_for_unknown_source_types():
    event = RawEvent(
        source_type="something_new", external_id="1", title="T", body="B", severity="high"
    )
    assert summarize(event) == "T. B"


# --- compute_dedupe_key -----------------------------------------------------


def test_compute_dedupe_key_is_deterministic():
    key1 = compute_dedupe_key("user-1", "disk_usage", "disk-2026-01-01")
    key2 = compute_dedupe_key("user-1", "disk_usage", "disk-2026-01-01")
    assert key1 == key2


def test_compute_dedupe_key_differs_when_any_component_differs():
    base = compute_dedupe_key("user-1", "disk_usage", "disk-2026-01-01")
    assert compute_dedupe_key("user-2", "disk_usage", "disk-2026-01-01") != base
    assert compute_dedupe_key("user-1", "docker_health", "disk-2026-01-01") != base
    assert compute_dedupe_key("user-1", "disk_usage", "disk-2026-01-02") != base
