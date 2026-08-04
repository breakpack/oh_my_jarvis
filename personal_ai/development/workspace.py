"""Git-worktree-based development sandbox (SPEC.md §9 Development Mode).

Implements the DevelopmentRuntime protocol (SPEC §9.3) via `git worktree`:
each workspace is an isolated branch checked out into its own directory
under WORKSPACE_BASE_DIR, so a Skill can search/read/patch/test a
repository without touching the caller's real working tree — and only
repositories explicitly listed in ALLOWED_REPOS can be used as a source at
all (SPEC §9.2: "명시되지 않은 저장소" is forbidden).

Commits are deliberately NOT implemented here. SPEC §12 requires an
approval gate before any external state change, and `git add` + `git
commit` is exactly that kind of mutation — it belongs in apps/api's
approval flow (a different worker's responsibility), not in this sandbox.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

WORKSPACE_BASE_DIR = Path(
    os.environ.get("WORKSPACE_BASE_DIR", str(Path.home() / "PersonalAI" / "workspaces"))
)
ALLOWED_REPOS = [p.strip() for p in os.environ.get("ALLOWED_REPOS", "").split(",") if p.strip()]

# SPEC §20.3: Shell allowlist. Every run_command call is checked against
# this before anything is spawned.
ALLOWED_COMMANDS = {"pytest", "ruff", "mypy", "python3", "uv", "npm", "git", "ls", "cat"}

_MAX_OUTPUT_CHARS = 20000
_MAX_SEARCH_RESULTS = 50

_WORKSPACE_SUBDIRS = ("artifacts", "logs", "patches", "test-results")


class WorkspaceNotFound(Exception):
    pass


class DevelopmentRuntime(Protocol):
    """SPEC §9.3."""

    async def create_workspace(self, source: str) -> str: ...

    async def search(self, workspace_id: str, query: str) -> list[dict]: ...

    async def read_file(self, workspace_id: str, path: str) -> str: ...

    async def apply_patch(self, workspace_id: str, patch: str) -> dict: ...

    async def run_command(self, workspace_id: str, command: list[str]) -> dict: ...

    async def get_diff(self, workspace_id: str) -> str: ...

    async def destroy_workspace(self, workspace_id: str) -> None: ...


class GitWorktreeRuntime:
    """SPEC §9.3 DevelopmentRuntime, backed by `git worktree` and a
    per-workspace directory tree (SPEC §9.2)."""

    def __init__(
        self,
        base_dir: Path | None = None,
        allowed_repos: list[str] | None = None,
    ) -> None:
        self._base_dir = Path(base_dir) if base_dir is not None else WORKSPACE_BASE_DIR
        raw_allowed = allowed_repos if allowed_repos is not None else ALLOWED_REPOS
        self._allowed_repos = [str(Path(p).resolve()) for p in raw_allowed]

    def _workspace_dir(self, workspace_id: str) -> Path:
        return self._base_dir / workspace_id

    def _repository_dir(self, workspace_id: str) -> Path:
        workspace_dir = self._workspace_dir(workspace_id)
        if not workspace_dir.is_dir():
            raise WorkspaceNotFound(workspace_id)
        return workspace_dir / "repository"

    async def create_workspace(self, source: str) -> str:
        source_path = str(Path(source).resolve())
        if source_path not in self._allowed_repos:
            raise PermissionError(f"repository not in ALLOWED_REPOS: {source}")

        workspace_id = str(uuid.uuid4())
        workspace_dir = self._workspace_dir(workspace_id)
        workspace_dir.mkdir(parents=True)
        for name in _WORKSPACE_SUBDIRS:
            (workspace_dir / name).mkdir()

        repository_dir = workspace_dir / "repository"
        branch = f"workspace/{workspace_id}"
        result = subprocess.run(
            ["git", "worktree", "add", str(repository_dir), "-b", branch],
            cwd=source_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

        metadata = {"source": source_path, "created_at": datetime.now(UTC).isoformat()}
        (workspace_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        return workspace_id

    async def search(self, workspace_id: str, query: str) -> list[dict]:
        repository_dir = self._repository_dir(workspace_id)
        matches: list[dict] = []
        for path in sorted(repository_dir.rglob("*")):
            if len(matches) >= _MAX_SEARCH_RESULTS:
                break
            if not path.is_file():
                continue
            if ".git" in path.relative_to(repository_dir).parts:
                continue

            if query.lower() in path.name.lower():
                matched_by = "filename"
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if query not in content:
                    continue
                matched_by = "content"

            matches.append(
                {"path": str(path.relative_to(repository_dir)), "matched_by": matched_by}
            )
        return matches

    async def read_file(self, workspace_id: str, path: str) -> str:
        repository_dir = self._repository_dir(workspace_id).resolve()
        # Resolution (not string matching on "..") is the actual defense —
        # it collapses "..", absolute-path overrides, and symlinks before
        # the containment check, so encoding tricks can't bypass it.
        candidate = (repository_dir / path).resolve()
        try:
            candidate.relative_to(repository_dir)
        except ValueError as exc:
            raise PermissionError(f"path escapes workspace repository: {path}") from exc
        if not candidate.is_file():
            raise FileNotFoundError(path)
        return candidate.read_text(encoding="utf-8")

    async def apply_patch(self, workspace_id: str, patch: str) -> dict:
        repository_dir = self._repository_dir(workspace_id)

        check = subprocess.run(
            ["git", "apply", "--check"],
            cwd=repository_dir,
            input=patch.encode(),
            capture_output=True,
            timeout=15,
        )
        if check.returncode != 0:
            return {"success": False, "stderr": check.stderr.decode(errors="replace")}

        applied = subprocess.run(
            ["git", "apply"],
            cwd=repository_dir,
            input=patch.encode(),
            capture_output=True,
            timeout=15,
        )
        return {
            "success": applied.returncode == 0,
            "stderr": applied.stderr.decode(errors="replace"),
        }

    async def run_command(self, workspace_id: str, command: list[str]) -> dict:
        if not command or command[0] not in ALLOWED_COMMANDS:
            raise PermissionError("command not allowed")

        repository_dir = self._repository_dir(workspace_id)
        started = time.monotonic()
        result = subprocess.run(
            command,
            cwd=repository_dir,
            shell=False,
            capture_output=True,
            timeout=120,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout.decode(errors="replace")[:_MAX_OUTPUT_CHARS],
            "stderr": result.stderr.decode(errors="replace")[:_MAX_OUTPUT_CHARS],
            "duration_ms": duration_ms,
        }

    async def get_diff(self, workspace_id: str) -> str:
        repository_dir = self._repository_dir(workspace_id)
        result = subprocess.run(
            ["git", "diff"],
            cwd=repository_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout

    async def destroy_workspace(self, workspace_id: str) -> None:
        workspace_dir = self._workspace_dir(workspace_id)
        if not workspace_dir.is_dir():
            return

        repository_dir = workspace_dir / "repository"
        metadata_path = workspace_dir / "metadata.json"
        source = None
        if metadata_path.is_file():
            try:
                source = json.loads(metadata_path.read_text(encoding="utf-8")).get("source")
            except (OSError, json.JSONDecodeError):
                source = None

        if source and repository_dir.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(repository_dir)],
                cwd=source,
                capture_output=True,
                timeout=30,
            )

        shutil.rmtree(workspace_dir, ignore_errors=True)
