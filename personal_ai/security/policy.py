"""Policy Engine — risk classification and approval gating (SPEC.md §3.5,
§12.1). Pure logic, no DB/HTTP: apps/api calls into this to decide whether
an action needs approval before it's allowed to run.
"""

from __future__ import annotations

RISK_LEVELS = ("read", "low_write", "medium", "high", "restricted")

# Phase 4's MCP adapter defaults every discovered tool to "confirm" (no
# risk metadata of its own); the Policy Engine only knows the SPEC §12.1
# levels, so "confirm" is treated as "medium".
_ALIASES = {"confirm": "medium"}

_APPROVAL_REQUIRED_LEVELS = {"medium", "high"}


class RestrictedActionError(Exception):
    """Raised for a RESTRICTED-risk action (SPEC §12.1: blocked outright,
    not something a user can approve their way past)."""


def normalize_risk_level(value: str) -> str:
    normalized = _ALIASES.get(value, value)
    if normalized not in RISK_LEVELS:
        raise ValueError(f"Unknown risk level: {value!r}")
    return normalized


def requires_approval(risk_level: str) -> bool:
    normalized = normalize_risk_level(risk_level)
    if normalized == "restricted":
        raise RestrictedActionError(
            f"Action risk level '{normalized}' is restricted and cannot be executed."
        )
    return normalized in _APPROVAL_REQUIRED_LEVELS
