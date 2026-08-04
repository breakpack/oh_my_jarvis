"""Unit tests for GithubIssuesTool (SPEC.md §7, §20.3). No real `gh` calls:
subprocess.run is monkeypatched with fake CompletedProcess results.
"""

from __future__ import annotations

import json
import subprocess

from personal_ai.tools import github as github_tool_module
from personal_ai.tools.base import ToolContext
from personal_ai.tools.github import GithubIssuesTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"github.read"},
)

_ISSUES_JSON = json.dumps(
    [
        {
            "number": 1,
            "title": "First issue",
            "state": "open",
            "url": "https://github.com/acme/widgets/issues/1",
            "createdAt": "2026-01-01T00:00:00Z",
        },
        {
            "number": 2,
            "title": "Second issue",
            "state": "open",
            "url": "https://github.com/acme/widgets/issues/2",
            "createdAt": "2026-01-02T00:00:00Z",
        },
    ]
)


def _fake_run_factory(*, returncode=0, stdout="", stderr="", raise_exc=None):
    calls = []

    def _fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    _fake_run.calls = calls
    return _fake_run


async def test_execute_returns_issues_and_evidence(monkeypatch):
    fake_run = _fake_run_factory(stdout=_ISSUES_JSON)
    monkeypatch.setattr(github_tool_module.subprocess, "run", fake_run)

    tool = GithubIssuesTool()
    result = await tool.execute({"repo": "acme/widgets", "state": "open", "limit": 5}, _CONTEXT)

    assert result.success is True
    assert result.error is None
    assert len(result.data["issues"]) == 2
    assert result.evidence[0]["source_type"] == "github_issue"
    assert result.evidence[0]["source_id"] == "acme/widgets#1"
    assert result.evidence[1]["metadata"]["url"] == "https://github.com/acme/widgets/issues/2"

    # Argument-list invocation, never a shell string.
    command, kwargs = fake_run.calls[0]
    assert isinstance(command, list)
    assert command[:3] == ["gh", "issue", "list"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 15


async def test_execute_wraps_gh_failure_in_tool_result_not_exception(monkeypatch):
    fake_run = _fake_run_factory(
        returncode=1, stderr="authentication required, run `gh auth login`"
    )
    monkeypatch.setattr(github_tool_module.subprocess, "run", fake_run)

    tool = GithubIssuesTool()
    result = await tool.execute({"repo": "acme/widgets"}, _CONTEXT)

    assert result.success is False
    assert "authentication required" in result.error


async def test_execute_wraps_timeout_in_tool_result(monkeypatch):
    fake_run = _fake_run_factory(raise_exc=subprocess.TimeoutExpired(cmd="gh", timeout=15))
    monkeypatch.setattr(github_tool_module.subprocess, "run", fake_run)

    tool = GithubIssuesTool()
    result = await tool.execute({"repo": "acme/widgets"}, _CONTEXT)

    assert result.success is False
    assert "timed out" in result.error


async def test_execute_missing_repo_never_calls_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when repo is missing")

    monkeypatch.setattr(github_tool_module.subprocess, "run", _boom)

    tool = GithubIssuesTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "repo" in result.error


async def test_execute_rejects_invalid_state(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for an invalid state")

    monkeypatch.setattr(github_tool_module.subprocess, "run", _boom)

    tool = GithubIssuesTool()
    result = await tool.execute({"repo": "acme/widgets", "state": "bogus"}, _CONTEXT)

    assert result.success is False
    assert "state" in result.error


async def test_dry_run_does_not_call_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called during dry_run")

    monkeypatch.setattr(github_tool_module.subprocess, "run", _boom)

    tool = GithubIssuesTool()
    result = await tool.dry_run({"repo": "acme/widgets", "limit": 5}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True
    assert "acme/widgets" in result.data["preview"]


async def test_verify_passes_through_when_within_limit(monkeypatch):
    fake_run = _fake_run_factory(stdout=_ISSUES_JSON)
    monkeypatch.setattr(github_tool_module.subprocess, "run", fake_run)

    tool = GithubIssuesTool()
    result = await tool.execute({"repo": "acme/widgets", "limit": 5}, _CONTEXT)
    verified = await tool.verify(result, _CONTEXT)

    assert verified.success is True
    assert len(verified.data["issues"]) == 2


async def test_verify_flags_more_issues_than_requested_limit():
    tool = GithubIssuesTool()
    from personal_ai.tools.base import ToolResult

    bogus_result = ToolResult(
        success=True,
        data={"issues": [{"number": i} for i in range(5)]},
        metadata={"requested_limit": 2},
    )
    verified = await tool.verify(bogus_result, _CONTEXT)

    assert verified.success is False


def test_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("github.list_issues")

    assert tool.name == "github.list_issues"
    assert tool.risk_level == "read"
    assert tool.required_scopes == {"github.read"}
    assert tool.input_schema["required"] == ["repo"]
    assert set(tool.input_schema["properties"]) == {"repo", "state", "limit"}
