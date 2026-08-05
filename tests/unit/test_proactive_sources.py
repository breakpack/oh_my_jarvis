"""Unit tests for personal_ai.proactive.sources (SPEC.md §13, Observe
stage). subprocess.run is monkeypatched throughout — no real gh/docker
calls — so only the parsing/threshold logic is under test.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from personal_ai.proactive import sources as sources_module
from personal_ai.proactive.sources import (
    DiskUsageSource,
    DockerHealthSource,
    GithubCIFailureSource,
)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# --- GithubCIFailureSource ---------------------------------------------


async def test_github_ci_failure_source_returns_empty_when_no_repos_configured(monkeypatch):
    monkeypatch.delenv("PROACTIVE_GITHUB_REPOS", raising=False)
    calls = []
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: calls.append(a) or _completed()
    )

    events = await GithubCIFailureSource().check()

    assert events == []
    assert calls == []  # never even attempted a subprocess call


async def test_github_ci_failure_source_parses_failed_runs(monkeypatch):
    monkeypatch.setenv("PROACTIVE_GITHUB_REPOS", "acme/widgets")
    runs = [
        {
            "databaseId": 123,
            "displayTitle": "Fix bug",
            "workflowName": "CI",
            "url": "https://github.com/acme/widgets/actions/runs/123",
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    ]

    captured_command = {}

    def fake_run(command, **kwargs):
        captured_command["command"] = command
        return _completed(stdout=json.dumps(runs))

    monkeypatch.setattr(sources_module.subprocess, "run", fake_run)

    events = await GithubCIFailureSource().check()

    assert len(events) == 1
    event = events[0]
    assert event.source_type == "github_ci_failure"
    assert event.external_id == "123"
    assert event.severity == "medium"
    assert "CI" in event.title
    assert "acme/widgets" in event.body

    command = captured_command["command"]
    assert isinstance(command, list)  # argument-list form, never a shell string
    assert command[0] == "gh"
    assert "--repo" in command and "acme/widgets" in command
    assert "--status" in command and "failure" in command


async def test_github_ci_failure_source_checks_every_configured_repo(monkeypatch):
    monkeypatch.setenv("PROACTIVE_GITHUB_REPOS", "acme/widgets, acme/gadgets")
    seen_repos = []

    def fake_run(command, **kwargs):
        repo_index = command.index("--repo") + 1
        seen_repos.append(command[repo_index])
        return _completed(stdout="[]")

    monkeypatch.setattr(sources_module.subprocess, "run", fake_run)

    await GithubCIFailureSource().check()

    assert seen_repos == ["acme/widgets", "acme/gadgets"]


@pytest.mark.parametrize(
    "fake_run",
    [
        lambda *a, **kw: _completed(returncode=1, stderr="not authenticated"),
        lambda *a, **kw: _completed(stdout="not json"),
        lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="gh", timeout=15)),
        lambda *a, **kw: (_ for _ in ()).throw(OSError("gh not found")),
    ],
)
async def test_github_ci_failure_source_swallows_failures_and_returns_empty(monkeypatch, fake_run):
    monkeypatch.setenv("PROACTIVE_GITHUB_REPOS", "acme/widgets")
    monkeypatch.setattr(sources_module.subprocess, "run", fake_run)

    events = await GithubCIFailureSource().check()

    assert events == []


# --- DiskUsageSource -----------------------------------------------------


def _disk_usage(percent_used: float) -> SimpleNamespace:
    total = 1000
    used = int(total * percent_used / 100)
    return SimpleNamespace(total=total, used=used, free=total - used)


async def test_disk_usage_source_below_threshold_returns_empty(monkeypatch):
    monkeypatch.setattr(sources_module.shutil, "disk_usage", lambda path: _disk_usage(89))

    assert await DiskUsageSource().check() == []


async def test_disk_usage_source_at_medium_threshold_is_medium(monkeypatch):
    monkeypatch.setattr(sources_module.shutil, "disk_usage", lambda path: _disk_usage(90))

    events = await DiskUsageSource().check()

    assert len(events) == 1
    assert events[0].severity == "medium"
    assert events[0].source_type == "disk_usage"


async def test_disk_usage_source_at_high_threshold_is_high(monkeypatch):
    monkeypatch.setattr(sources_module.shutil, "disk_usage", lambda path: _disk_usage(95))

    events = await DiskUsageSource().check()

    assert len(events) == 1
    assert events[0].severity == "high"


async def test_disk_usage_source_just_below_high_threshold_is_medium(monkeypatch):
    monkeypatch.setattr(sources_module.shutil, "disk_usage", lambda path: _disk_usage(94.9))

    events = await DiskUsageSource().check()

    assert len(events) == 1
    assert events[0].severity == "medium"


async def test_disk_usage_source_external_id_is_fixed_per_day(monkeypatch):
    monkeypatch.setattr(sources_module.shutil, "disk_usage", lambda path: _disk_usage(96))

    events = await DiskUsageSource().check()

    assert events[0].external_id.startswith("disk-")


# --- DockerHealthSource --------------------------------------------------


def _container_line(**fields) -> str:
    base = {
        "ID": "abc123",
        "Names": "some-container",
        "Image": "some-image",
        "Status": "Up 2 hours",
    }
    base.update(fields)
    return json.dumps(base)


async def test_docker_health_source_returns_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("PROACTIVE_DOCKER_CONTAINERS", raising=False)
    calls = []
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: calls.append(a) or _completed()
    )

    events = await DockerHealthSource().check()

    assert events == []
    assert calls == []  # never even attempted a subprocess call


async def test_docker_health_source_ignores_unwatched_container_names(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "compose")
    stdout = _container_line(Names="unrelated-project", Status="Exited (1) now") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    assert await DockerHealthSource().check() == []


async def test_docker_health_source_flags_unhealthy_status(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = _container_line(Status="Up 2 hours (unhealthy)") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    events = await DockerHealthSource().check()

    assert len(events) == 1
    assert events[0].severity == "high"
    assert events[0].source_type == "docker_health"
    assert events[0].external_id == "abc123"


async def test_docker_health_source_flags_abnormal_exit(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = _container_line(Status="Exited (1) 5 minutes ago") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    events = await DockerHealthSource().check()

    assert len(events) == 1
    assert events[0].severity == "high"


async def test_docker_health_source_ignores_clean_exit(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = _container_line(Status="Exited (0) 5 minutes ago") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    assert await DockerHealthSource().check() == []


async def test_docker_health_source_ignores_healthy_running_containers(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = _container_line(Status="Up 3 hours (healthy)") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    assert await DockerHealthSource().check() == []


async def test_docker_health_source_handles_multiple_lines_and_mixed_health(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = "\n".join(
        [
            _container_line(ID="1", Status="Up 1 hour (healthy)"),
            _container_line(ID="2", Status="Up 1 hour (unhealthy)"),
            _container_line(ID="3", Status="Exited (0) 1 hour ago"),
            _container_line(ID="4", Status="Exited (137) 1 hour ago"),
        ]
    )
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    events = await DockerHealthSource().check()

    assert {e.external_id for e in events} == {"2", "4"}


async def test_docker_health_source_skips_malformed_json_lines(monkeypatch):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    stdout = "not json at all\n" + _container_line(ID="2", Status="Exited (1) now") + "\n"
    monkeypatch.setattr(
        sources_module.subprocess, "run", lambda *a, **kw: _completed(stdout=stdout)
    )

    events = await DockerHealthSource().check()

    assert len(events) == 1
    assert events[0].external_id == "2"


@pytest.mark.parametrize(
    "fake_run",
    [
        lambda *a, **kw: _completed(returncode=1, stderr="docker: command not found"),
        lambda *a, **kw: (_ for _ in ()).throw(OSError("docker not found")),
        lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="docker", timeout=15)),
    ],
)
async def test_docker_health_source_swallows_failures_and_returns_empty(monkeypatch, fake_run):
    monkeypatch.setenv("PROACTIVE_DOCKER_CONTAINERS", "some-container")
    monkeypatch.setattr(sources_module.subprocess, "run", fake_run)

    assert await DockerHealthSource().check() == []
