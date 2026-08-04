"""Unit tests for personal_ai.skills.store (SPEC.md §6.8 Skill Store,
§25 DoD "버전 Rollback"). Real filesystem operations under tmp_path — no
mocking beyond overriding SKILL_STORE_BASE_DIR for isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from personal_ai.skills import store as store_module
from personal_ai.skills.store import (
    PathTraversalError,
    SourceNotADirectoryError,
    activate_skill_version,
    copy_skill_files,
    install_skill_files,
)


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "my-skill-source"
    (source / "sub").mkdir(parents=True)
    (source / "manifest.yaml").write_text("hello: world", encoding="utf-8")
    (source / "sub" / "nested.txt").write_text("nested content", encoding="utf-8")
    return source


# --- copy_skill_files ------------------------------------------------------


def test_copy_skill_files_preserves_directory_structure(tmp_path):
    source = _make_source(tmp_path)
    dest = tmp_path / "dest"

    copy_skill_files(source, dest)

    assert (dest / "manifest.yaml").read_text(encoding="utf-8") == "hello: world"
    assert (dest / "sub" / "nested.txt").read_text(encoding="utf-8") == "nested content"


def test_copy_skill_files_rejects_a_plain_file_as_source(tmp_path):
    not_a_dir = tmp_path / "plainfile.txt"
    not_a_dir.write_text("x", encoding="utf-8")

    with pytest.raises(SourceNotADirectoryError):
        copy_skill_files(not_a_dir, tmp_path / "dest")


def test_copy_skill_files_rejects_a_missing_source(tmp_path):
    with pytest.raises(SourceNotADirectoryError):
        copy_skill_files(tmp_path / "does-not-exist", tmp_path / "dest")


def test_copy_skill_files_blocks_symlink_escaping_source_dir(tmp_path):
    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("do not leak this", encoding="utf-8")

    source = tmp_path / "evil-skill"
    source.mkdir()
    (source / "manifest.yaml").write_text("ok", encoding="utf-8")
    (source / "escape-link").symlink_to(outside_secret)

    dest = tmp_path / "evil-dest"
    with pytest.raises(PathTraversalError):
        copy_skill_files(source, dest)

    # The traversal is caught before any copying starts, so nothing —
    # not even the legitimate manifest.yaml alongside the symlink —
    # should have been written.
    assert not dest.exists()


def test_copy_skill_files_blocks_symlinked_subdirectory_escaping_source_dir(tmp_path):
    outside_dir = tmp_path / "outside-dir"
    (outside_dir).mkdir()
    (outside_dir / "secret.txt").write_text("nope", encoding="utf-8")

    source = tmp_path / "evil-skill-2"
    source.mkdir()
    (source / "manifest.yaml").write_text("ok", encoding="utf-8")
    (source / "escape-dir-link").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(PathTraversalError):
        copy_skill_files(source, tmp_path / "evil-dest-2")


def test_copy_skill_files_skips_broken_symlinks_without_erroring(tmp_path):
    # The dangling target must resolve to somewhere *within* source_dir —
    # a target outside it is (correctly, and more strictly than asked)
    # treated as a traversal attempt regardless of whether it exists, per
    # test_copy_skill_files_blocks_symlink_escaping_source_dir.
    source = tmp_path / "dangling-link-skill"
    source.mkdir()
    (source / "manifest.yaml").write_text("ok", encoding="utf-8")
    (source / "dangling-link").symlink_to(source / "sibling-does-not-exist.txt")

    dest = tmp_path / "dangling-dest"
    copy_skill_files(source, dest)  # must not raise

    assert (dest / "manifest.yaml").read_text(encoding="utf-8") == "ok"
    assert not (dest / "dangling-link").exists()


# --- install_skill_files ----------------------------------------------------


def test_install_skill_files_writes_under_name_and_version(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SKILL_STORE_BASE_DIR", tmp_path / "store")
    source = _make_source(tmp_path)

    installed_path = install_skill_files("my-skill", "1.0.0", source)

    assert installed_path == tmp_path / "store" / "my-skill" / "1.0.0"
    assert (installed_path / "manifest.yaml").read_text(encoding="utf-8") == "hello: world"


def test_install_skill_files_keeps_versions_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SKILL_STORE_BASE_DIR", tmp_path / "store")
    source = _make_source(tmp_path)

    v1_path = install_skill_files("my-skill", "1.0.0", source)

    (source / "manifest.yaml").write_text("hello: v2", encoding="utf-8")
    v2_path = install_skill_files("my-skill", "2.0.0", source)

    assert (v1_path / "manifest.yaml").read_text(encoding="utf-8") == "hello: world"
    assert (v2_path / "manifest.yaml").read_text(encoding="utf-8") == "hello: v2"


# --- activate_skill_version (install / update / rollback) ------------------


def test_activate_skill_version_copies_into_live_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SKILL_STORE_BASE_DIR", tmp_path / "store")
    source = _make_source(tmp_path)
    v1_path = install_skill_files("my-skill", "1.0.0", source)
    live_dir = tmp_path / "live-skills"

    activate_skill_version("my-skill", v1_path, live_dir)

    assert (live_dir / "my-skill" / "manifest.yaml").read_text(encoding="utf-8") == "hello: world"
    assert (live_dir / "my-skill" / "sub" / "nested.txt").is_file()


def test_activate_skill_version_rollback_replaces_previous_content(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SKILL_STORE_BASE_DIR", tmp_path / "store")
    source = _make_source(tmp_path)
    v1_path = install_skill_files("my-skill", "1.0.0", source)

    (source / "manifest.yaml").write_text("hello: v2", encoding="utf-8")
    (source / "v2-only.txt").write_text("only in v2", encoding="utf-8")
    v2_path = install_skill_files("my-skill", "2.0.0", source)

    live_dir = tmp_path / "live-skills"
    activate_skill_version("my-skill", v2_path, live_dir)
    assert (live_dir / "my-skill" / "manifest.yaml").read_text(encoding="utf-8") == "hello: v2"
    assert (live_dir / "my-skill" / "v2-only.txt").is_file()

    # Roll back to v1: the file that only existed in v2 must be gone
    # afterwards, since activation replaces the live directory wholesale.
    activate_skill_version("my-skill", v1_path, live_dir)

    assert (live_dir / "my-skill" / "manifest.yaml").read_text(encoding="utf-8") == "hello: world"
    assert not (live_dir / "my-skill" / "v2-only.txt").exists()


def test_activate_skill_version_full_install_update_rollback_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "SKILL_STORE_BASE_DIR", tmp_path / "store")
    source = _make_source(tmp_path)
    live_dir = tmp_path / "live-skills"

    v1_path = install_skill_files("cycle-skill", "1.0.0", source)
    activate_skill_version("cycle-skill", v1_path, live_dir)
    assert (live_dir / "cycle-skill" / "manifest.yaml").read_text(encoding="utf-8") == (
        "hello: world"
    )

    (source / "manifest.yaml").write_text("hello: v2", encoding="utf-8")
    v2_path = install_skill_files("cycle-skill", "2.0.0", source)
    activate_skill_version("cycle-skill", v2_path, live_dir)
    assert (live_dir / "cycle-skill" / "manifest.yaml").read_text(encoding="utf-8") == "hello: v2"

    activate_skill_version("cycle-skill", v1_path, live_dir)
    assert (live_dir / "cycle-skill" / "manifest.yaml").read_text(encoding="utf-8") == (
        "hello: world"
    )
