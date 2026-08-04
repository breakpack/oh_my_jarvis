"""Unit tests for GithubCreateIssueTool / GithubCloseIssueTool (SPEC.md §7,
§12.1 MEDIUM: Issue 생성 → 승인). No real `gh` calls: subprocess.run is
monkeypatched with fake CompletedProcess results.
"""

from __future__ import annotations

import subprocess

from personal_ai.tools import github_write as github_write_module
from personal_ai.tools.base import ToolContext
from personal_ai.tools.github_write import GithubCloseIssueTool, GithubCreateIssueTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"github.write"},
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


# --- GithubCreateIssueTool ---------------------------------------------


async def test_create_execute_returns_number_and_url_from_gh_output(monkeypatch):
    fake_run = _fake_run_factory(stdout="https://github.com/acme/widgets/issues/42\n")
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCreateIssueTool()
    result = await tool.execute(
        {"repo": "acme/widgets", "title": "Bug found", "body": "Details here"}, _CONTEXT
    )

    assert result.success is True
    assert result.error is None
    assert result.data == {"number": 42, "url": "https://github.com/acme/widgets/issues/42"}
    assert result.evidence[0]["source_type"] == "github_issue"
    assert result.evidence[0]["source_id"] == "acme/widgets#42"
    assert result.evidence[0]["metadata"]["url"] == "https://github.com/acme/widgets/issues/42"

    # Argument-list invocation, never a shell string. No --json (gh issue
    # create doesn't support it — see module docstring).
    command, kwargs = fake_run.calls[0]
    assert isinstance(command, list)
    assert command[:3] == ["gh", "issue", "create"]
    assert "--json" not in command
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 15


async def test_create_execute_defaults_body_to_empty_string(monkeypatch):
    fake_run = _fake_run_factory(stdout="https://github.com/acme/widgets/issues/7\n")
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "title": "No body"}, _CONTEXT)

    assert result.success is True
    command, _ = fake_run.calls[0]
    body_index = command.index("--body")
    assert command[body_index + 1] == ""


async def test_create_execute_wraps_gh_failure_in_tool_result_not_exception(monkeypatch):
    fake_run = _fake_run_factory(
        returncode=1, stderr="authentication required, run `gh auth login`"
    )
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "title": "Bug"}, _CONTEXT)

    assert result.success is False
    assert "authentication required" in result.error


async def test_create_execute_wraps_timeout_in_tool_result(monkeypatch):
    fake_run = _fake_run_factory(raise_exc=subprocess.TimeoutExpired(cmd="gh", timeout=15))
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "title": "Bug"}, _CONTEXT)

    assert result.success is False
    assert "timed out" in result.error


async def test_create_execute_unparseable_output_is_reported_as_error(monkeypatch):
    fake_run = _fake_run_factory(stdout="not a url\n")
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "title": "Bug"}, _CONTEXT)

    assert result.success is False
    assert "could not parse issue number" in result.error


async def test_create_execute_missing_repo_never_calls_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when repo is missing")

    monkeypatch.setattr(github_write_module.subprocess, "run", _boom)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"title": "Bug"}, _CONTEXT)

    assert result.success is False
    assert "repo" in result.error


async def test_create_execute_missing_title_never_calls_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when title is missing")

    monkeypatch.setattr(github_write_module.subprocess, "run", _boom)

    tool = GithubCreateIssueTool()
    result = await tool.execute({"repo": "acme/widgets"}, _CONTEXT)

    assert result.success is False
    assert "title" in result.error


async def test_create_dry_run_does_not_call_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called during dry_run")

    monkeypatch.setattr(github_write_module.subprocess, "run", _boom)

    tool = GithubCreateIssueTool()
    result = await tool.dry_run({"repo": "acme/widgets", "title": "Bug"}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True
    assert "acme/widgets" in result.data["preview"]
    assert "Bug" in result.data["preview"]


# --- GithubCloseIssueTool ------------------------------------------------


async def test_close_execute_success(monkeypatch):
    fake_run = _fake_run_factory(stdout="Closed issue #42\n")
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCloseIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "issue_number": 42}, _CONTEXT)

    assert result.success is True
    assert result.data == {"issue_number": 42, "repo": "acme/widgets"}
    assert result.evidence[0]["source_id"] == "acme/widgets#42"

    command, kwargs = fake_run.calls[0]
    assert command == ["gh", "issue", "close", "42", "--repo", "acme/widgets"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 15


async def test_close_execute_wraps_gh_failure_in_tool_result_not_exception(monkeypatch):
    fake_run = _fake_run_factory(returncode=1, stderr="issue not found")
    monkeypatch.setattr(github_write_module.subprocess, "run", fake_run)

    tool = GithubCloseIssueTool()
    result = await tool.execute({"repo": "acme/widgets", "issue_number": 999}, _CONTEXT)

    assert result.success is False
    assert "issue not found" in result.error


async def test_close_execute_missing_issue_number_never_calls_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when issue_number is missing")

    monkeypatch.setattr(github_write_module.subprocess, "run", _boom)

    tool = GithubCloseIssueTool()
    result = await tool.execute({"repo": "acme/widgets"}, _CONTEXT)

    assert result.success is False
    assert "issue_number" in result.error


async def test_close_dry_run_does_not_call_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called during dry_run")

    monkeypatch.setattr(github_write_module.subprocess, "run", _boom)

    tool = GithubCloseIssueTool()
    result = await tool.dry_run({"repo": "acme/widgets", "issue_number": 42}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True
    assert "42" in result.data["preview"]


# --- Registration ---------------------------------------------------------


def test_create_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("github.create_issue")

    assert tool.name == "github.create_issue"
    assert tool.risk_level == "medium"
    assert tool.required_scopes == {"github.write"}
    assert tool.input_schema["required"] == ["repo", "title"]
    assert set(tool.input_schema["properties"]) == {"repo", "title", "body"}


def test_close_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("github.close_issue")

    assert tool.name == "github.close_issue"
    assert tool.risk_level == "medium"
    assert tool.required_scopes == {"github.write"}
    assert tool.input_schema["required"] == ["repo", "issue_number"]
    assert set(tool.input_schema["properties"]) == {"repo", "issue_number"}
