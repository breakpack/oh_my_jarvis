"""Obsidian vault search tool — read-only, local files only (SPEC.md §7,
§20 Path Traversal). Mirrors personal_ai.tools.files.LocalFileSearchTool's
resolve-then-contain traversal defense, scoped to OBSIDIAN_VAULT_PATH
instead of WORKSPACE_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_MAX_RESULTS = 50
_SNIPPET_CHARS = 300


def _vault_root() -> Path | None:
    root = os.environ.get("OBSIDIAN_VAULT_PATH")
    return Path(root).resolve() if root else None


def _resolve_within_vault(vault_root: Path, note_path: str) -> Path | None:
    """Resolution (not string matching on "..") is the actual defense: it
    collapses "..", symlinks, and any other traversal trick before the
    containment check."""
    candidate = (vault_root / note_path).resolve()
    try:
        candidate.relative_to(vault_root)
    except ValueError:
        return None
    return candidate


def _snippet_around(content: str, query: str) -> str:
    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[:_SNIPPET_CHARS]
    start = max(0, idx - _SNIPPET_CHARS // 2)
    return content[start : start + _SNIPPET_CHARS]


class ObsidianSearchTool:
    name = "obsidian.search_notes"
    description = (
        "목적: 로컬 Obsidian 볼트(OBSIDIAN_VAULT_PATH)에서 노트를 파일명/내용으로 "
        "검색하거나, path를 지정해 특정 노트 전체를 읽는다. "
        "언제 사용: 사용자가 자신의 Obsidian 노트에서 특정 주제/키워드를 찾아달라고 "
        "하거나, 특정 노트의 전체 내용을 보여달라고 할 때 사용한다. "
        "언제 사용하면 안 되는지: 노트를 생성/수정/삭제하는 용도로는 사용할 수 없다 "
        "(조회 전용); 볼트 밖의 경로는 조회할 수 없다. "
        "입력 의미: query는 파일명 또는 내용에서 찾을 문자열, path는 볼트 루트 "
        "기준 상대경로의 특정 노트(.md) — 둘 중 하나는 필수이며 path가 있으면 "
        "query는 무시하고 그 노트 전체를 반환한다. "
        "외부 영향: 없음 — 로컬 마크다운 파일을 읽기만 하며 아무것도 변경하지 않는다. "
        "반환값: data.notes에 각 노트의 path/matched_by/snippet(검색 시) 또는 "
        "path/content(단일 노트 조회 시)가 담긴 리스트. "
        "오류 조건: OBSIDIAN_VAULT_PATH가 설정되지 않았거나 존재하지 않는 경우, "
        "query와 path가 둘 다 없는 경우, path가 볼트를 벗어나거나(Path Traversal "
        "시도 포함) 존재하지 않는 경우 — 이 모든 경우 success=False와 error 메시지로 "
        "반환한다. "
        "승인 필요 여부: risk_level=read이므로 SPEC §12.1에 따라 자동 실행 가능 — "
        "승인 불필요."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "파일명 또는 내용에서 찾을 문자열",
            },
            "path": {
                "type": "string",
                "description": "볼트 루트 기준 상대경로의 특정 노트를 전체 조회 "
                "(지정 시 query 무시)",
            },
        },
    }
    risk_level = "read"
    required_scopes = {"obsidian.read"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        note_path = arguments.get("path")
        query = arguments.get("query", "")
        preview = (
            f"노트 '{note_path}' 전체 조회 예정" if note_path else f"볼트에서 '{query}' 검색 예정"
        )
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        vault_root = _vault_root()
        if vault_root is None:
            return ToolResult(
                success=False,
                error="OBSIDIAN_VAULT_PATH가 설정되지 않았습니다. .env에 볼트 경로를 설정하세요.",
            )
        if not vault_root.is_dir():
            return ToolResult(success=False, error=f"vault path not found: {vault_root}")

        note_path = arguments.get("path")
        if note_path:
            resolved = _resolve_within_vault(vault_root, note_path)
            if resolved is None:
                return ToolResult(success=False, error="path outside vault root")
            if not resolved.is_file():
                return ToolResult(success=False, error=f"note not found: {note_path}")
            try:
                content = resolved.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                return ToolResult(success=False, error=f"failed to read note: {exc}")
            return ToolResult(
                success=True,
                data={"notes": [{"path": note_path, "content": content}]},
                evidence=[
                    {
                        "source_type": "obsidian_note",
                        "source_id": note_path,
                        "title": note_path,
                        "content": content[:_SNIPPET_CHARS],
                    }
                ],
            )

        query = arguments.get("query")
        if not query:
            return ToolResult(success=False, error="query or path is required")

        matches: list[dict[str, str]] = []
        for path in vault_root.rglob("*.md"):
            if len(matches) >= _MAX_RESULTS:
                break
            rel = str(path.relative_to(vault_root))
            if query.lower() in path.stem.lower():
                try:
                    snippet = path.read_text(encoding="utf-8")[:_SNIPPET_CHARS]
                except (UnicodeDecodeError, OSError):
                    snippet = ""
                matches.append({"path": rel, "matched_by": "filename", "snippet": snippet})
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if query.lower() not in content.lower():
                continue
            matches.append(
                {"path": rel, "matched_by": "content", "snippet": _snippet_around(content, query)}
            )

        evidence = [
            {
                "source_type": "obsidian_note",
                "source_id": m["path"],
                "title": m["path"],
                "content": m["snippet"],
                "metadata": {"matched_by": m["matched_by"]},
            }
            for m in matches
        ]
        return ToolResult(success=True, data={"notes": matches}, evidence=evidence)

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        if result.success and result.data is not None:
            notes = result.data.get("notes", [])
            if len(notes) > _MAX_RESULTS:
                return ToolResult(
                    success=False,
                    error=f"returned {len(notes)} notes, more than the {_MAX_RESULTS} limit",
                )
        return result


default_tool_registry.register(ObsidianSearchTool())
