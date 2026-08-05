"""Event sources for the proactive assistant (SPEC.md §13, Observe stage).

Every source is best-effort and self-contained: one that can't reach its
backend (no gh auth, docker not running, repo not configured, ...) returns
an empty list instead of raising, so a broken source never blocks the
others or the pipeline that calls them.

DockerHealthSource only watches containers whose name contains one of the
PROACTIVE_DOCKER_CONTAINERS substrings (comma-separated env var); empty
(the default) means the source does nothing. This Mac routinely runs
unrelated Docker containers from other projects, so unscoped whole-machine
monitoring would be noisy by default — scope it explicitly to opt in. It
only ever reads (`docker ps -a`); nothing here starts, stops, or touches
any container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date
from typing import Protocol

from pydantic import BaseModel

_GH_TIMEOUT_SECONDS = 15
_GH_RUN_LIMIT = 5
_DOCKER_TIMEOUT_SECONDS = 15

_DISK_MEDIUM_THRESHOLD = 90.0
_DISK_HIGH_THRESHOLD = 95.0


class RawEvent(BaseModel):
    source_type: str
    external_id: str  # stable within the source; feeds compute_dedupe_key
    title: str
    body: str
    severity: str  # "low" | "medium" | "high" — the source's first guess;
    # the pipeline (should_suggest) makes the final call.


class EventSource(Protocol):
    name: str

    async def check(self) -> list[RawEvent]: ...


def _github_repos() -> list[str]:
    raw = os.environ.get("PROACTIVE_GITHUB_REPOS", "")
    return [repo.strip() for repo in raw.split(",") if repo.strip()]


class GithubCIFailureSource:
    name = "github_ci_failure"

    async def check(self) -> list[RawEvent]:
        events: list[RawEvent] = []
        for repo in _github_repos():
            events.extend(self._check_repo(repo))
        return events

    def _check_repo(self, repo: str) -> list[RawEvent]:
        command = [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--status",
            "failure",
            "--limit",
            str(_GH_RUN_LIMIT),
            "--json",
            "databaseId,displayTitle,workflowName,url,updatedAt",
        ]
        try:
            proc = subprocess.run(  # noqa: S603 — argument list, shell=False, timeout set
                command,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
                shell=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

        if proc.returncode != 0:
            return []

        try:
            runs = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []

        return [
            RawEvent(
                source_type=self.name,
                external_id=str(run.get("databaseId")),
                title=f"CI 실패: {run.get('workflowName', '?')} — {run.get('displayTitle', '?')}",
                body=f"{repo}: {run.get('url', '')}",
                severity="medium",
            )
            for run in runs
        ]


class DiskUsageSource:
    name = "disk_usage"

    async def check(self) -> list[RawEvent]:
        usage = shutil.disk_usage("/")
        percent_used = (usage.used / usage.total * 100) if usage.total else 0.0

        if percent_used >= _DISK_HIGH_THRESHOLD:
            severity = "high"
        elif percent_used >= _DISK_MEDIUM_THRESHOLD:
            severity = "medium"
        else:
            return []

        # Fixed to today's date so the dedupe key only changes once a day,
        # instead of firing a fresh "event" on every single check.
        return [
            RawEvent(
                source_type=self.name,
                external_id=f"disk-{date.today()}",
                title=f"디스크 사용률 {percent_used:.1f}%",
                body=f"루트 디스크(/)가 {percent_used:.1f}% 사용 중입니다.",
                severity=severity,
            )
        ]


def _is_unhealthy_status(status: str) -> bool:
    if "unhealthy" in status:
        return True
    # Docker's Status string for a stopped container looks like
    # "Exited (0) 5 minutes ago" — a non-zero exit code is abnormal.
    return status.startswith("Exited") and not status.startswith("Exited (0)")


def _docker_containers() -> list[str]:
    raw = os.environ.get("PROACTIVE_DOCKER_CONTAINERS", "")
    return [name.strip() for name in raw.split(",") if name.strip()]


class DockerHealthSource:
    name = "docker_health"

    async def check(self) -> list[RawEvent]:
        watched = _docker_containers()
        if not watched:
            return []

        command = ["docker", "ps", "-a", "--format", "{{json .}}"]
        try:
            proc = subprocess.run(  # noqa: S603 — argument list, shell=False, timeout set
                command,
                capture_output=True,
                text=True,
                timeout=_DOCKER_TIMEOUT_SECONDS,
                shell=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []

        if proc.returncode != 0:
            return []

        events: list[RawEvent] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                container = json.loads(line)
            except json.JSONDecodeError:
                continue

            names = container.get("Names", "")
            if not any(watch in names for watch in watched):
                continue

            status = container.get("Status", "")
            if not _is_unhealthy_status(status):
                continue

            events.append(
                RawEvent(
                    source_type=self.name,
                    external_id=container.get("ID", ""),
                    title=f"컨테이너 이상: {container.get('Names', '?')}",
                    body=f"{container.get('Image', '?')} — 상태: {status}",
                    severity="high",
                )
            )
        return events
