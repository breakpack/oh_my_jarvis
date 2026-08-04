"""Workspace escape tests (SPEC.md §25 DoD "Workspace escape 테스트",
§20.3 Shell 제약). Real git commands against a throwaway dummy repo under
pytest's tmp_path — never the oh_my_jarvis repo itself.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from personal_ai.development.workspace import ALLOWED_COMMANDS, GitWorktreeRuntime


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, timeout=15)


@pytest.fixture
def dummy_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "dummy-repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    (repo / "hello.py").write_text('print("hello")\n')
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


@pytest.fixture
def runtime(tmp_path: Path, dummy_repo: Path) -> GitWorktreeRuntime:
    return GitWorktreeRuntime(base_dir=tmp_path / "workspaces", allowed_repos=[str(dummy_repo)])


@pytest.fixture
async def workspace_id(dummy_repo, runtime):
    ws_id = await runtime.create_workspace(str(dummy_repo))
    yield ws_id
    await runtime.destroy_workspace(ws_id)


@pytest.fixture
def canary_file(tmp_path: Path) -> Path:
    """A file well outside the workspace/repo that a successful escape
    would be able to read or write."""
    canary = tmp_path / "outside-the-sandbox" / "secret.txt"
    canary.parent.mkdir(parents=True)
    canary.write_text("do-not-touch")
    return canary


async def test_read_file_rejects_relative_traversal(runtime, workspace_id, canary_file):
    relative_traversal = "../" * 10 + str(canary_file).lstrip("/")

    with pytest.raises(PermissionError):
        await runtime.read_file(workspace_id, relative_traversal)
    with pytest.raises(PermissionError):
        await runtime.read_file(workspace_id, "../../../etc/passwd")


async def test_read_file_rejects_absolute_path(runtime, workspace_id, canary_file):
    with pytest.raises(PermissionError):
        await runtime.read_file(workspace_id, "/etc/passwd")
    with pytest.raises(PermissionError):
        await runtime.read_file(workspace_id, str(canary_file))


async def test_read_file_rejects_symlink_escape(tmp_path, runtime, workspace_id, canary_file):
    repository_dir = tmp_path / "workspaces" / workspace_id / "repository"
    symlink = repository_dir / "escape-link"
    symlink.symlink_to(canary_file)

    with pytest.raises(PermissionError):
        await runtime.read_file(workspace_id, "escape-link")


async def test_apply_patch_does_not_write_outside_the_repository(
    tmp_path, runtime, workspace_id, canary_file
):
    original_contents = canary_file.read_text()
    repository_dir = tmp_path / "workspaces" / workspace_id / "repository"
    # A patch path that, if git followed it naively, would land exactly on
    # the canary file outside the repository.
    relative_target = os.path.relpath(canary_file, repository_dir)

    escaping_patch = (
        f"--- a/{relative_target}\n+++ b/{relative_target}\n@@ -1 +1 @@\n-do-not-touch\n+pwned\n"
    )

    result = await runtime.apply_patch(workspace_id, escaping_patch)

    # Whether git rejects the path outright or the apply otherwise fails,
    # the canary file must be untouched either way.
    assert canary_file.read_text() == original_contents
    if result["success"]:
        pytest.fail(f"apply_patch reported success for an escaping patch: {result}")


@pytest.mark.parametrize(
    "command",
    [
        ["rm", "-rf", "/"],
        ["curl", "http://example.com"],
        ["bash", "-c", "echo pwned"],
        ["sh", "-c", "echo pwned"],
    ],
)
async def test_run_command_blocks_disallowed_commands(runtime, workspace_id, command):
    with pytest.raises(PermissionError):
        await runtime.run_command(workspace_id, command)


async def test_run_command_blocks_empty_command(runtime, workspace_id):
    with pytest.raises(PermissionError):
        await runtime.run_command(workspace_id, [])


def test_allowlist_does_not_include_shell_escape_hatches():
    # A hard guarantee about the allowlist itself, not just behavior: no
    # shell/interpreter-with-eval command should ever be addable here.
    assert ALLOWED_COMMANDS == {
        "pytest",
        "ruff",
        "mypy",
        "python3",
        "uv",
        "npm",
        "git",
        "ls",
        "cat",
    }
    assert "bash" not in ALLOWED_COMMANDS
    assert "sh" not in ALLOWED_COMMANDS
    assert "rm" not in ALLOWED_COMMANDS
