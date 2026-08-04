"""Unit tests for personal_ai.security.policy (SPEC.md §12.1). Pure
functions, no mocking needed.
"""

from __future__ import annotations

import pytest

from personal_ai.security.policy import (
    RISK_LEVELS,
    RestrictedActionError,
    normalize_risk_level,
    requires_approval,
)


def test_risk_levels_match_spec_table():
    assert RISK_LEVELS == ("read", "low_write", "medium", "high", "restricted")


def test_normalize_risk_level_maps_confirm_to_medium():
    assert normalize_risk_level("confirm") == "medium"


@pytest.mark.parametrize("level", RISK_LEVELS)
def test_normalize_risk_level_is_identity_for_known_levels(level):
    assert normalize_risk_level(level) == level


def test_normalize_risk_level_rejects_unknown_value():
    with pytest.raises(ValueError, match="Unknown risk level"):
        normalize_risk_level("nonsense")


@pytest.mark.parametrize("level", ["read", "low_write"])
def test_requires_approval_is_false_for_read_and_low_write(level):
    assert requires_approval(level) is False


@pytest.mark.parametrize("level", ["medium", "high"])
def test_requires_approval_is_true_for_medium_and_high(level):
    assert requires_approval(level) is True


def test_requires_approval_treats_confirm_as_medium():
    assert requires_approval("confirm") is True


def test_requires_approval_raises_for_restricted():
    with pytest.raises(RestrictedActionError):
        requires_approval("restricted")
