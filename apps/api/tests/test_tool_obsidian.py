"""Unit tests for ObsidianSearchTool (SPEC.md §7, §20 Path Traversal). Uses
a real temp directory as the vault — no mocking needed for local file I/O.
"""

from __future__ import annotations

from pathlib import Path

from personal_ai.tools import obsidian as obsidian_module
from personal_ai.tools.base import ToolContext
from personal_ai.tools.obsidian import ObsidianSearchTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"obsidian.read"},
)


def _vault(tmp_path: Path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    return vault


async def test_execute_without_vault_path_configured(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    tool = ObsidianSearchTool()
    result = await tool.execute({"query": "x"}, _CONTEXT)

    assert result.success is False
    assert "OBSIDIAN_VAULT_PATH" in result.error


async def test_execute_requires_query_or_path(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)

    tool = ObsidianSearchTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "required" in result.error


async def test_execute_matches_by_filename(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    (vault / "Weekly Review.md").write_text("nothing relevant here", encoding="utf-8")

    tool = ObsidianSearchTool()
    result = await tool.execute({"query": "weekly"}, _CONTEXT)

    assert result.success is True
    assert len(result.data["notes"]) == 1
    assert result.data["notes"][0]["matched_by"] == "filename"


async def test_execute_matches_by_content(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    (vault / "note.md").write_text("this mentions project alpha somewhere", encoding="utf-8")

    tool = ObsidianSearchTool()
    result = await tool.execute({"query": "project alpha"}, _CONTEXT)

    assert result.success is True
    assert len(result.data["notes"]) == 1
    assert result.data["notes"][0]["matched_by"] == "content"
    assert "project alpha" in result.data["notes"][0]["snippet"]


async def test_execute_reads_single_note_by_path(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    (vault / "note.md").write_text("full content here", encoding="utf-8")

    tool = ObsidianSearchTool()
    result = await tool.execute({"path": "note.md"}, _CONTEXT)

    assert result.success is True
    assert result.data["notes"] == [{"path": "note.md", "content": "full content here"}]


async def test_execute_rejects_path_traversal(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)
    (tmp_path / "secret.md").write_text("outside the vault", encoding="utf-8")

    tool = ObsidianSearchTool()
    result = await tool.execute({"path": "../secret.md"}, _CONTEXT)

    assert result.success is False
    assert "outside vault root" in result.error


async def test_execute_missing_note_path(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)

    tool = ObsidianSearchTool()
    result = await tool.execute({"path": "missing.md"}, _CONTEXT)

    assert result.success is False
    assert "not found" in result.error


async def test_execute_only_matches_markdown_files(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    (vault / "data.txt").write_text("keyword here", encoding="utf-8")

    tool = ObsidianSearchTool()
    result = await tool.execute({"query": "keyword"}, _CONTEXT)

    assert result.success is True
    assert result.data["notes"] == []


def test_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("obsidian.search_notes")

    assert tool.name == "obsidian.search_notes"
    assert tool.risk_level == "read"
    assert tool.required_scopes == {"obsidian.read"}


def test_vault_root_helper_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert obsidian_module._vault_root() is None
