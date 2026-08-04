"""Full-lifecycle tests for GitWorktreeRuntime (SPEC.md §9.2, §9.3, §25 DoD
"테스트 작성 및 실행"). Real git commands against a throwaway dummy repo
under pytest's tmp_path — never the oh_my_jarvis repo itself.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from personal_ai.development.workspace import GitWorktreeRuntime, WorkspaceNotFound


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
    (repo / "README.md").write_text("# Dummy repo\nTODO: write docs\n")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


@pytest.fixture
def runtime(tmp_path: Path, dummy_repo: Path) -> GitWorktreeRuntime:
    return GitWorktreeRuntime(base_dir=tmp_path / "workspaces", allowed_repos=[str(dummy_repo)])


async def test_create_workspace_rejects_repo_not_in_allowlist(tmp_path, runtime):
    not_allowed = tmp_path / "not-allowed-repo"
    not_allowed.mkdir()

    with pytest.raises(PermissionError):
        await runtime.create_workspace(str(not_allowed))


async def test_create_workspace_builds_expected_layout(tmp_path, dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))

    workspace_dir = tmp_path / "workspaces" / workspace_id
    repository_dir = workspace_dir / "repository"
    assert (repository_dir / "hello.py").is_file()
    for sub in ("artifacts", "logs", "patches", "test-results"):
        assert (workspace_dir / sub).is_dir()

    metadata = json.loads((workspace_dir / "metadata.json").read_text())
    assert metadata["source"] == str(dummy_repo.resolve())
    assert "created_at" in metadata

    # A real git worktree, registered against the source repo.
    worktree_list = _run(["git", "worktree", "list"], dummy_repo).stdout
    assert str(repository_dir) in worktree_list

    await runtime.destroy_workspace(workspace_id)


async def test_search_finds_matches_by_filename_and_content(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        by_filename = await runtime.search(workspace_id, "hello")
        assert {"path": "hello.py", "matched_by": "filename"} in by_filename

        by_content = await runtime.search(workspace_id, "TODO")
        assert {"path": "README.md", "matched_by": "content"} in by_content

        no_match = await runtime.search(workspace_id, "nonexistent-token-xyz")
        assert no_match == []
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_read_file_returns_contents(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        content = await runtime.read_file(workspace_id, "hello.py")
        assert content == 'print("hello")\n'
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_read_file_missing_file_raises(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        with pytest.raises(FileNotFoundError):
            await runtime.read_file(workspace_id, "does-not-exist.py")
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_apply_patch_applies_a_real_patch(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        patch = '--- a/hello.py\n+++ b/hello.py\n@@ -1 +1,2 @@\n print("hello")\n+print("world")\n'
        result = await runtime.apply_patch(workspace_id, patch)
        assert result == {"success": True, "stderr": ""}

        content = await runtime.read_file(workspace_id, "hello.py")
        assert "world" in content

        diff = await runtime.get_diff(workspace_id)
        assert '+print("world")' in diff
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_apply_patch_reports_failure_for_unapplicable_patch(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        bogus_patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1 +1 @@\n"
            "-this line does not exist in the file\n"
            '+print("nope")\n'
        )
        result = await runtime.apply_patch(workspace_id, bogus_patch)
        assert result["success"] is False
        assert result["stderr"]

        # A failed apply must not have modified the file.
        content = await runtime.read_file(workspace_id, "hello.py")
        assert content == 'print("hello")\n'
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_run_command_executes_a_real_allowed_command(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        result = await runtime.run_command(workspace_id, ["git", "status", "--short"])
        assert result["exit_code"] == 0
        assert isinstance(result["stdout"], str)
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_run_command_executes_pytest_against_the_workspace(dummy_repo, runtime):
    (dummy_repo / "test_trivial.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    _run(["git", "add", "-A"], dummy_repo)
    _run(["git", "commit", "-m", "add test"], dummy_repo)

    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        result = await runtime.run_command(
            workspace_id, ["pytest", "test_trivial.py", "-q", "--no-header"]
        )
        assert result["exit_code"] == 0
        assert "1 passed" in result["stdout"]
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_run_command_truncates_output_to_20000_chars(dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    try:
        result = await runtime.run_command(workspace_id, ["python3", "-c", "print('x' * 30000)"])
        assert result["exit_code"] == 0
        assert len(result["stdout"]) == 20000
    finally:
        await runtime.destroy_workspace(workspace_id)


async def test_destroy_workspace_removes_directory_and_worktree(tmp_path, dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))
    workspace_dir = tmp_path / "workspaces" / workspace_id

    await runtime.destroy_workspace(workspace_id)

    assert not workspace_dir.exists()
    worktree_list = _run(["git", "worktree", "list"], dummy_repo).stdout
    assert str(workspace_dir / "repository") not in worktree_list


async def test_destroy_workspace_is_idempotent_for_unknown_id(runtime):
    # Destroying a workspace that never existed must not raise.
    await runtime.destroy_workspace("does-not-exist")


async def test_operations_on_unknown_workspace_raise_workspace_not_found(runtime):
    with pytest.raises(WorkspaceNotFound):
        await runtime.search("does-not-exist", "query")
    with pytest.raises(WorkspaceNotFound):
        await runtime.read_file("does-not-exist", "hello.py")


async def test_full_lifecycle(tmp_path, dummy_repo, runtime):
    workspace_id = await runtime.create_workspace(str(dummy_repo))

    matches = await runtime.search(workspace_id, "hello")
    assert matches

    original = await runtime.read_file(workspace_id, "hello.py")
    assert original == 'print("hello")\n'

    patch_result = await runtime.apply_patch(
        workspace_id,
        '--- a/hello.py\n+++ b/hello.py\n@@ -1 +1,2 @@\n print("hello")\n+print("lifecycle")\n',
    )
    assert patch_result["success"] is True

    run_result = await runtime.run_command(workspace_id, ["git", "log", "--oneline", "-1"])
    assert run_result["exit_code"] == 0

    diff = await runtime.get_diff(workspace_id)
    assert "lifecycle" in diff

    await runtime.destroy_workspace(workspace_id)
    assert not (tmp_path / "workspaces" / workspace_id).exists()
