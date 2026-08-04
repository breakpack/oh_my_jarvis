"""Unit tests for personal_ai.security.approval (SPEC.md §12.2, §12.3).
Pure functions, no mocking needed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from personal_ai.security.approval import (
    ApprovalRequest,
    build_approval_request,
    compute_arguments_hash,
    verify_arguments_unchanged,
)


def test_compute_arguments_hash_is_independent_of_key_order():
    a = compute_arguments_hash({"a": 1, "b": 2})
    b = compute_arguments_hash({"b": 2, "a": 1})

    assert a == b
    assert len(a) == 64  # sha256 hex digest


def test_compute_arguments_hash_changes_when_a_value_changes():
    original = compute_arguments_hash({"amount": 10})
    tampered = compute_arguments_hash({"amount": 11})

    assert original != tampered


def test_compute_arguments_hash_handles_non_json_native_values_via_default_str():
    # `default=str` is what makes this not blow up on e.g. a datetime value.
    result = compute_arguments_hash({"when": datetime(2026, 1, 1, tzinfo=UTC)})

    assert isinstance(result, str)
    assert len(result) == 64


def test_build_approval_request_returns_request_and_matching_hash():
    request, arguments_hash = build_approval_request(
        action="calendar.create_event",
        target="calendar:primary",
        risk_level="medium",
        arguments={"title": "Sync", "start": "2026-01-01T10:00:00"},
        preview="Create event 'Sync' on 2026-01-01",
        expected_effects=["calendar event created"],
        rollback_available=True,
    )

    assert isinstance(request, ApprovalRequest)
    assert request.action == "calendar.create_event"
    assert request.target == "calendar:primary"
    assert request.risk_level == "medium"
    assert request.preview == "Create event 'Sync' on 2026-01-01"
    assert request.expected_effects == ["calendar event created"]
    assert request.rollback_available is True
    assert arguments_hash == compute_arguments_hash(request.arguments)


def test_build_approval_request_generates_distinct_uuids_for_id_and_agent_run_id():
    request, _ = build_approval_request(
        action="a",
        target="t",
        risk_level="high",
        arguments={},
        preview="p",
        expected_effects=[],
        rollback_available=False,
    )

    assert request.id != request.agent_run_id
    # Both must actually be UUIDs, not placeholder strings.
    import uuid

    uuid.UUID(request.id)
    uuid.UUID(request.agent_run_id)


def test_build_approval_request_sets_expires_at_in_the_future():
    before = datetime.now(UTC)

    request, _ = build_approval_request(
        action="a",
        target="t",
        risk_level="high",
        arguments={},
        preview="p",
        expected_effects=[],
        rollback_available=False,
        expires_in_seconds=60,
    )

    expires_at = datetime.fromisoformat(request.expires_at)
    assert expires_at > before
    assert (expires_at - before).total_seconds() <= 61  # allow a hair of slack


def test_build_approval_request_default_expiry_is_one_day():
    before = datetime.now(UTC)

    request, _ = build_approval_request(
        action="a",
        target="t",
        risk_level="high",
        arguments={},
        preview="p",
        expected_effects=[],
        rollback_available=False,
    )

    expires_at = datetime.fromisoformat(request.expires_at)
    delta_seconds = (expires_at - before).total_seconds()
    assert 86399 <= delta_seconds <= 86401


def test_verify_arguments_unchanged_true_when_untouched():
    arguments = {"to": "a@example.com", "subject": "hi"}
    _, stored_hash = build_approval_request(
        action="email.send",
        target="a@example.com",
        risk_level="high",
        arguments=arguments,
        preview="Send email",
        expected_effects=["email sent"],
        rollback_available=False,
    )

    assert verify_arguments_unchanged(arguments, stored_hash) is True


def test_verify_arguments_unchanged_false_when_tampered():
    arguments = {"to": "a@example.com", "subject": "hi"}
    _, stored_hash = build_approval_request(
        action="email.send",
        target="a@example.com",
        risk_level="high",
        arguments=arguments,
        preview="Send email",
        expected_effects=["email sent"],
        rollback_available=False,
    )

    tampered_arguments = {"to": "attacker@example.com", "subject": "hi"}

    assert verify_arguments_unchanged(tampered_arguments, stored_hash) is False
