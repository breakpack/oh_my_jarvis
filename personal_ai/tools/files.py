"""Local file search tool (SPEC.md §7, §20 Path Traversal)."""

from __future__ import annotations

import os
from pathlib import Path

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_MAX_RESULTS = 50


def _workspace_root() -> Path:
    root = os.environ.get("WORKSPACE_ROOT")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _resolve_within_root(root_arg: str) -> Path | None:
    """Resolve `root_arg` under the workspace root, or None if it escapes it.

    Resolution (not string matching on "..") is the actual defense: it
    collapses "..", symlinks, and any other traversal trick before the
    containment check, so it can't be bypassed by encoding tricks that a
    naive substring check on ".." would miss.
    """
    workspace_root = _workspace_root()
    candidate = (workspace_root / root_arg).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError:
        return None
    return candidate


class LocalFileSearchTool:
    name = "files.search"
    description = (
        "목적: 워크스페이스 루트 이하에서 파일명 또는 파일 내용에 검색어가 포함된 "
        "파일을 찾는다. "
        "언제 사용: 사용자가 로컬 파일/코드에서 특정 이름이나 문자열을 찾아달라고 "
        "요청할 때 사용한다. "
        "언제 사용하면 안 되는지: 파일을 생성/수정/삭제하는 용도로는 사용할 수 없다 "
        "(조회 전용이며 파일시스템을 변경하지 않는다); 워크스페이스 루트(환경변수 "
        "WORKSPACE_ROOT, 없으면 현재 작업 디렉터리) 밖의 경로는 조회할 수 없다. "
        "입력 의미: query는 파일명 또는 파일 내용에서 찾을 문자열(필수), root는 "
        "워크스페이스 루트 기준 검색 시작 상대 경로(생략 시 루트 전체). "
        "외부 영향: 없음 — 로컬 파일을 읽기만 하며 아무것도 변경하지 않는다. "
        "반환값: data.matches에 각 일치 파일의 path(워크스페이스 루트 기준 상대 "
        "경로)와 matched_by(filename|content)가 담긴 리스트, 최대 50개. "
        "오류 조건: query가 비어있는 경우, root가 워크스페이스 루트를 벗어나는 "
        "경로(Path Traversal 시도 포함)인 경우, root가 존재하지 않거나 디렉터리가 "
        "아닌 경우 — 이 모든 경우 success=False와 error 메시지로 반환하며 파일시스템 "
        "접근을 시도하지 않는다. "
        "승인 필요 여부: risk_level=read이므로 SPEC §12.1에 따라 자동 실행 가능 — "
        "승인 불필요."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "파일명 또는 내용에서 찾을 문자열 (필수)",
            },
            "root": {
                "type": "string",
                "description": "검색 루트 상대경로, 생략시 워크스페이스 루트 전체",
            },
        },
        "required": ["query"],
    }
    risk_level = "read"
    required_scopes = {"files.read"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        query = arguments.get("query", "")
        root = arguments.get("root", ".")
        preview = f"워크스페이스 루트 하위 '{root}'에서 '{query}' 검색 예정 (최대 {_MAX_RESULTS}개)"
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        query = arguments.get("query")
        if not query:
            return ToolResult(success=False, error="query is required")

        root_arg = arguments.get("root") or "."
        workspace_root = _workspace_root()
        search_root = _resolve_within_root(root_arg)
        if search_root is None:
            return ToolResult(success=False, error="path outside workspace root")
        if not search_root.exists() or not search_root.is_dir():
            return ToolResult(success=False, error=f"root not found or not a directory: {root_arg}")

        matches: list[dict[str, str]] = []
        for path in search_root.rglob("*"):
            if len(matches) >= _MAX_RESULTS:
                break
            if not path.is_file():
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
                {
                    "path": str(path.relative_to(workspace_root)),
                    "matched_by": matched_by,
                }
            )

        evidence = [
            {
                "source_type": "local_file",
                "source_id": match["path"],
                "title": match["path"],
                "content": f"matched by {match['matched_by']}",
                "metadata": {"matched_by": match["matched_by"]},
            }
            for match in matches
        ]
        return ToolResult(success=True, data={"matches": matches}, evidence=evidence)

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        if result.success and result.data is not None:
            matches = result.data.get("matches", [])
            if len(matches) > _MAX_RESULTS:
                return ToolResult(
                    success=False,
                    error=f"returned {len(matches)} matches, more than the {_MAX_RESULTS} limit",
                )
        return result


default_tool_registry.register(LocalFileSearchTool())
