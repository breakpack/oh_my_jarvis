"""GitHub Issues read tool (SPEC.md §7, §20.3)."""

from __future__ import annotations

import json
import subprocess

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_VALID_STATES = {"open", "closed", "all"}
_GH_TIMEOUT_SECONDS = 15


class GithubIssuesTool:
    name = "github.list_issues"
    description = (
        "목적: 지정된 GitHub 저장소의 이슈 목록을 조회한다. "
        "언제 사용: 사용자가 특정 저장소의 열려있는/닫힌 이슈 현황을 묻거나, "
        "이슈 기반 evidence가 필요한 질의(Query)에 답할 때 사용한다. "
        "언제 사용하면 안 되는지: 이슈를 생성/수정/코멘트하거나 저장소 상태를 "
        "변경하는 용도로는 사용할 수 없다 (본 Tool은 조회 전용이며 그런 쓰기 동작을 "
        "수행하지 않는다); 저장소가 비공개이고 필요한 GitHub 인증이 없는 환경에서는 "
        "실패로 응답하므로 사전에 인증 상태를 가정하지 말 것. "
        "입력 의미: repo는 'owner/name' 형식의 저장소 식별자(필수), state는 "
        "open|closed|all 중 하나(기본 open), limit은 가져올 최대 이슈 개수(기본 20). "
        "외부 영향: 없음 — GitHub API에 읽기 요청만 보내며 어떤 상태도 변경하지 않는다. "
        "반환값: data.issues에 각 이슈의 number/title/state/url/createdAt이 담긴 "
        "리스트, evidence에 동일 이슈들을 evidence 레코드(source_type=github_issue, "
        "source_id=repo#number)로 변환한 목록. "
        "오류 조건: repo가 없거나 형식이 잘못된 경우, GitHub CLI(gh) 인증이 안 된 "
        "경우, 저장소가 존재하지 않거나 접근 권한이 없는 경우, 명령이 15초 안에 "
        "끝나지 않는 경우 — 이 모든 경우 success=False와 error 메시지로 반환하며 "
        "예외를 던지지 않는다. "
        "승인 필요 여부: risk_level=read이므로 SPEC §12.1에 따라 자동 실행 가능 — "
        "승인 불필요."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "조회할 저장소, 'owner/name' 형식 (필수)",
            },
            "state": {
                "type": "string",
                "enum": sorted(_VALID_STATES),
                "default": "open",
                "description": "이슈 상태 필터",
            },
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "가져올 최대 이슈 개수",
            },
        },
        "required": ["repo"],
    }
    risk_level = "read"
    required_scopes = {"github.read"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo", "")
        state = arguments.get("state", "open")
        limit = arguments.get("limit", 20)
        preview = f"GitHub 저장소 '{repo}'에서 이슈 최대 {limit}개(state={state}) 조회 예정"
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo")
        if not repo:
            return ToolResult(success=False, error="repo is required")

        state = arguments.get("state", "open")
        if state not in _VALID_STATES:
            return ToolResult(
                success=False,
                error=f"invalid state '{state}', expected one of {sorted(_VALID_STATES)}",
            )

        try:
            limit = int(arguments.get("limit", 20))
        except (TypeError, ValueError):
            return ToolResult(success=False, error="limit must be an integer")
        if limit <= 0:
            return ToolResult(success=False, error="limit must be positive")

        command = [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,state,url,createdAt",
        ]
        try:
            proc = subprocess.run(  # noqa: S603 — argument list, shell=False, timeout set
                command,
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, error=f"gh issue list timed out after {_GH_TIMEOUT_SECONDS}s"
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"failed to run gh: {exc}")

        if proc.returncode != 0:
            return ToolResult(
                success=False, error=(proc.stderr or "gh issue list failed").strip()[:500]
            )

        try:
            issues = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return ToolResult(success=False, error=f"failed to parse gh output: {exc}")

        evidence = [
            {
                "source_type": "github_issue",
                "source_id": f"{repo}#{issue.get('number')}",
                "title": issue.get("title", ""),
                "content": issue.get("title", ""),
                "metadata": {
                    "url": issue.get("url"),
                    "state": issue.get("state"),
                    "createdAt": issue.get("createdAt"),
                },
            }
            for issue in issues
        ]
        return ToolResult(
            success=True,
            data={"issues": issues},
            evidence=evidence,
            metadata={"requested_limit": limit},
        )

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        if result.success and result.data is not None:
            requested_limit = result.metadata.get("requested_limit")
            issues = result.data.get("issues", [])
            if requested_limit is not None and len(issues) > requested_limit:
                return ToolResult(
                    success=False,
                    error=(
                        f"gh returned {len(issues)} issues, "
                        f"more than requested limit {requested_limit}"
                    ),
                )
        return result


default_tool_registry.register(GithubIssuesTool())
