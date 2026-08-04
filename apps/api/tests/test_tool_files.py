"""Unit tests for LocalFileSearchTool (SPEC.md §7, §20 Path Traversal).
Uses tmp_path to run real searches against real files — no mocking.
"""

from __future__ import annotations

from personal_ai.tools.base import ToolContext
from personal_ai.tools.files import LocalFileSearchTool
from personal_ai.tools.registry import default_tool_registry

_CONTEXT = ToolContext(
    user_id="user-1",
    conversation_id="conv-1",
    project_id=None,
    workspace_id=None,
    granted_scopes={"files.read"},
)


def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    return tmp_path


async def test_execute_matches_by_filename(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    (workspace / "invoice_report.txt").write_text("nothing relevant here")
    (workspace / "other.txt").write_text("also nothing")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "invoice"}, _CONTEXT)

    assert result.success is True
    paths = {m["path"] for m in result.data["matches"]}
    assert paths == {"invoice_report.txt"}
    assert result.data["matches"][0]["matched_by"] == "filename"
    assert result.evidence[0]["source_type"] == "local_file"


async def test_execute_matches_by_content(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    (workspace / "notes.txt").write_text("the secret phrase is xylophone42")
    (workspace / "unrelated.txt").write_text("just some other text")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "xylophone42"}, _CONTEXT)

    assert result.success is True
    assert [m["path"] for m in result.data["matches"]] == ["notes.txt"]
    assert result.data["matches"][0]["matched_by"] == "content"


async def test_execute_searches_within_given_subdirectory(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    sub = workspace / "sub"
    sub.mkdir()
    (sub / "target.txt").write_text("findme")
    (workspace / "target.txt").write_text("also findme but outside sub")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "target", "root": "sub"}, _CONTEXT)

    assert result.success is True
    assert [m["path"] for m in result.data["matches"]] == ["sub/target.txt"]


async def test_execute_skips_binary_files_without_crashing(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    (workspace / "image.bin").write_bytes(bytes(range(256)))
    (workspace / "readable.txt").write_text("query_needle present here")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "query_needle"}, _CONTEXT)

    assert result.success is True
    assert [m["path"] for m in result.data["matches"]] == ["readable.txt"]


async def test_execute_caps_results_at_fifty(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    for i in range(60):
        (workspace / f"match_{i}.txt").write_text("filler")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "match_"}, _CONTEXT)

    assert result.success is True
    assert len(result.data["matches"]) == 50


async def test_execute_rejects_root_path_traversal_without_touching_filesystem(
    tmp_path, monkeypatch
):
    workspace = _workspace(tmp_path, monkeypatch)
    (workspace / "inside.txt").write_text("should never be reached")

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "inside", "root": "../../etc"}, _CONTEXT)

    assert result.success is False
    assert result.error == "path outside workspace root"
    assert result.data is None


async def test_execute_rejects_absolute_path_escaping_root(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)

    tool = LocalFileSearchTool()
    result = await tool.execute({"query": "passwd", "root": "/etc"}, _CONTEXT)

    assert result.success is False
    assert result.error == "path outside workspace root"


async def test_execute_missing_query_is_an_error():
    tool = LocalFileSearchTool()
    result = await tool.execute({}, _CONTEXT)

    assert result.success is False
    assert "query" in result.error


async def test_dry_run_does_not_touch_filesystem(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)

    tool = LocalFileSearchTool()
    result = await tool.dry_run({"query": "anything", "root": "sub"}, _CONTEXT)

    assert result.success is True
    assert result.metadata["dry_run"] is True
    assert "anything" in result.data["preview"]


def test_tool_is_registered_with_expected_schema():
    tool = default_tool_registry.get("files.search")

    assert tool.name == "files.search"
    assert tool.risk_level == "read"
    assert tool.required_scopes == {"files.read"}
    assert tool.input_schema["required"] == ["query"]
    assert set(tool.input_schema["properties"]) == {"query", "root"}
