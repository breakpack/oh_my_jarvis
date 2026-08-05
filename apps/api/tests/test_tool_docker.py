"""Unit tests for DockerStatusTool (SPEC.md §7, §20.3). No real `docker`
calls: subprocess.run is monkeypatched with fake CompletedProcess results.
"""

from __future__ import annotations

import json
import subprocess

from personal_ai.tools import docker as docker_tool_module
from personal_ai.tools.base import ToolContext
from personal_ai.tools.docker import DockerStatusTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"docker.read"},
)


def _container_line(**fields) -> str:
    base = {
        "ID": "abc123",
        "Names": "some-container",
        "Image": "some-image",
        "Status": "Up 2 hours",
    }
    base.update(fields)
    return json.dumps(base)


def _fake_run_factory(*, returncode=0, stdout="", stderr="", raise_exc=None):
    calls = []

    def _fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    _fake_run.calls = calls
    return _fake_run


async def test_execute_returns_containers(monkeypatch):
    stdout = "\n".join([_container_line(ID="1"), _container_line(ID="2", Names="other")])
    fake_run = _fake_run_factory(stdout=stdout)
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is True
    assert result.error is None
    assert len(result.data["containers"]) == 2

    command, kwargs = fake_run.calls[0]
    assert isinstance(command, list)  # argument-list form, never a shell string
    assert command[:3] == ["docker", "ps", "-a"]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 15


async def test_execute_empty_container_list_is_success_not_failure(monkeypatch):
    fake_run = _fake_run_factory(stdout="")
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is True
    assert result.data["containers"] == []


async def test_execute_skips_malformed_json_lines(monkeypatch):
    stdout = "not json at all\n" + _container_line(ID="2")
    fake_run = _fake_run_factory(stdout=stdout)
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert len(result.data["containers"]) == 1
    assert result.data["containers"][0]["ID"] == "2"


async def test_execute_wraps_docker_failure_in_tool_result_not_exception(monkeypatch):
    fake_run = _fake_run_factory(returncode=1, stderr="Cannot connect to the Docker daemon")
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "Docker daemon" in result.error


async def test_execute_wraps_timeout_in_tool_result(monkeypatch):
    fake_run = _fake_run_factory(raise_exc=subprocess.TimeoutExpired(cmd="docker", timeout=15))
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "timed out" in result.error


async def test_execute_wraps_missing_binary_in_tool_result(monkeypatch):
    fake_run = _fake_run_factory(raise_exc=OSError("docker not found"))
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "docker" in result.error


async def test_dry_run_does_not_call_subprocess(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called during dry_run")

    monkeypatch.setattr(docker_tool_module.subprocess, "run", _boom)

    tool = DockerStatusTool()
    result = await tool.dry_run({}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True


async def test_verify_passes_through_empty_result(monkeypatch):
    fake_run = _fake_run_factory(stdout="")
    monkeypatch.setattr(docker_tool_module.subprocess, "run", fake_run)

    tool = DockerStatusTool()
    result = await tool.execute({}, _CONTEXT)
    verified = await tool.verify(result, _CONTEXT)

    assert verified.success is True
    assert verified.data["containers"] == []


def test_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("docker.list_containers")

    assert tool.name == "docker.list_containers"
    assert tool.risk_level == "read"
    assert tool.required_scopes == {"docker.read"}
    assert tool.input_schema["properties"] == {}
