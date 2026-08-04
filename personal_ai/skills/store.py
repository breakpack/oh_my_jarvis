"""Skill Store: local filesystem install/version-management (SPEC.md §6.8
Skill Store — local directory install only in this phase, no remote
registry; §6.9 supply-chain path traversal defense).

install_skill_files keeps every installed version around under
SKILL_STORE_BASE_DIR/<name>/<version>/, which is what makes
activate_skill_version able to roll back: "installing" an older version
again is just re-activating a copy that was never deleted.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

SKILL_STORE_BASE_DIR = Path(
    os.environ.get("SKILL_STORE_BASE_DIR", str(Path.home() / "PersonalAI" / "skill_store"))
)


class SourceNotADirectoryError(Exception):
    pass


class PathTraversalError(Exception):
    pass


def copy_skill_files(source_dir: Path, dest_dir: Path) -> None:
    """Copy every file under `source_dir` into `dest_dir`, preserving the
    directory structure. Rejects (raises, copies nothing partial) if
    `source_dir` isn't a real directory, or if anything inside it —
    typically a symlink — resolves outside `source_dir` itself."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise SourceNotADirectoryError(f"not a directory: {source_dir}")

    source_root = source_dir.resolve()
    entries = sorted(source_dir.rglob("*"))

    # Validate every entry stays within source_root *before* copying
    # anything, so a traversal attempt anywhere in the package aborts the
    # whole install instead of leaving a partial copy behind.
    for path in entries:
        resolved = path.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise PathTraversalError(f"path escapes source_dir: {path}") from exc

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in entries:
        relative = path.resolve().relative_to(source_root)
        target = dest_dir / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path.resolve(), target)
        # A symlink whose target doesn't exist is neither a file nor a
        # directory — silently skipped rather than treated as an error.
        # (A dangling target outside source_root would already have been
        # rejected above as a traversal attempt, existing or not.)


def install_skill_files(name: str, version: str, source_dir: Path) -> Path:
    """Copy `source_dir` into the version-addressed store location and
    return that path — this is the "install a specific version" step."""
    dest_dir = SKILL_STORE_BASE_DIR / name / version
    copy_skill_files(source_dir, dest_dir)
    return dest_dir


def activate_skill_version(name: str, store_path: Path, live_skills_dir: Path) -> None:
    """Make `store_path` the live version of skill `name` under
    `live_skills_dir` — the actual install/update/rollback point: whatever
    was there before is replaced wholesale with `store_path`'s contents."""
    live_dir = Path(live_skills_dir) / name
    if live_dir.exists():
        shutil.rmtree(live_dir)
    copy_skill_files(store_path, live_dir)
