"""GitHub Issue write tools (SPEC.md §7, §12.1 MEDIUM: Issue 생성 → 승인, §20.3).

GithubCreateIssueTool is a real, approval-gated write (risk_level=medium) —
it must never be called without prior user approval; that gate is enforced
by the Skill/Orchestrator layer above this module, not here.

GithubCloseIssueTool exists to serve as GithubCreateIssueTool's rollback
(closing the issue undoes creating it, SPEC §12.3) rather than as a
general-purpose "close any issue" feature offered on its own.

Note on `gh issue create`: unlike `gh issue list` (personal_ai.tools.github),
the real `gh` CLI's `issue create` subcommand has no `--json` flag (verified
via `gh issue create --help`) — on success it prints only the created
issue's URL to stdout. The issue number is parsed out of that URL instead.
"""

from __future__ import annotations

import re
import subprocess

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_GH_TIMEOUT_SECONDS = 15
_ISSUE_URL_NUMBER_RE = re.compile(r"/issues/(\d+)")


class GithubCreateIssueTool:
    name = "github.create_issue"
    description = (
        "목적: 지정된 GitHub 저장소에 새 이슈를 생성한다. "
        "언제 사용: 사용자가 명시적으로 GitHub 이슈 생성을 요청했고, 그 요청이 승인된 "
        "뒤에만 사용한다. "
        "언제 사용하면 안 되는지: 승인 없이 호출해서는 안 된다 (risk_level=medium, "
        "SPEC §12.1에 따라 실행 전 승인 필수); 이슈 조회에는 이 Tool 대신 읽기 전용 "
        "github.list_issues를 사용한다. "
        "입력 의미: repo는 'owner/name' 형식의 저장소 식별자(필수), title은 이슈 "
        "제목(필수), body는 이슈 본문(선택, 생략 시 빈 문자열). "
        "외부 영향: GitHub 저장소에 실제 이슈가 생성됨 — 완전히 삭제할 수는 없지만 "
        "github.close_issue로 닫아 롤백할 수 있다. "
        "반환값: data에 생성된 이슈의 number와 url, evidence에 해당 이슈를 가리키는 "
        "evidence 레코드(source_type=github_issue, source_id=repo#number). "
        "오류 조건: repo/title이 없는 경우, GitHub CLI(gh) 인증이 안 된 경우, 저장소가 "
        "존재하지 않거나 쓰기 권한이 없는 경우, 명령이 15초 안에 끝나지 않는 경우, gh가 "
        "예상한 이슈 URL 형식을 반환하지 않는 경우 — 이 모든 경우 success=False와 "
        "error 메시지로 반환하며 예외를 던지지 않는다. "
        "승인 필요 여부: risk_level=medium이므로 SPEC §12.1에 따라 실행 전 사용자 승인이 "
        "반드시 필요하다 — Skill/Orchestrator는 승인 없이 이 Tool을 호출하지 않는다."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "이슈를 생성할 저장소, 'owner/name' 형식 (필수)",
            },
            "title": {
                "type": "string",
                "description": "이슈 제목 (필수)",
            },
            "body": {
                "type": "string",
                "description": "이슈 본문 (선택, 생략 시 빈 문자열)",
            },
        },
        "required": ["repo", "title"],
    }
    risk_level = "medium"
    required_scopes = {"github.write"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo", "")
        title = arguments.get("title", "")
        preview = f"GitHub 저장소 '{repo}'에 제목 '{title}'로 새 이슈를 생성할 예정"
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo")
        if not repo:
            return ToolResult(success=False, error="repo is required")
        title = arguments.get("title")
        if not title:
            return ToolResult(success=False, error="title is required")
        body = arguments.get("body") or ""

        command = [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
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
                success=False, error=f"gh issue create timed out after {_GH_TIMEOUT_SECONDS}s"
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"failed to run gh: {exc}")

        if proc.returncode != 0:
            return ToolResult(
                success=False, error=(proc.stderr or "gh issue create failed").strip()[:500]
            )

        url = proc.stdout.strip()
        match = _ISSUE_URL_NUMBER_RE.search(url)
        if not match:
            return ToolResult(
                success=False, error=f"could not parse issue number from gh output: {url!r}"
            )
        number = int(match.group(1))

        evidence = [
            {
                "source_type": "github_issue",
                "source_id": f"{repo}#{number}",
                "title": title,
                "content": body,
                "metadata": {"url": url},
            }
        ]
        return ToolResult(success=True, data={"number": number, "url": url}, evidence=evidence)

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        return result


class GithubCloseIssueTool:
    name = "github.close_issue"
    description = (
        "목적: 지정된 GitHub 저장소의 이슈를 닫는다. "
        "언제 사용: github.create_issue로 생성한 이슈를 롤백(취소)할 때, 또는 사용자가 "
        "명시적으로 승인한 뒤 특정 이슈를 닫아 달라고 요청했을 때 사용한다. "
        "언제 사용하면 안 되는지: 이슈를 다시 열거나 삭제하는 용도로는 사용할 수 없다 "
        "(닫기 전용이며, 독립적인 승인 없는 임의 호출도 허용되지 않는다). "
        "입력 의미: repo는 'owner/name' 형식의 저장소 식별자(필수), issue_number는 "
        "닫을 이슈 번호(필수). "
        "외부 영향: GitHub 저장소의 해당 이슈 상태가 closed로 변경됨. "
        "반환값: data에 닫힌 이슈의 issue_number와 repo, evidence에 해당 이슈를 "
        "가리키는 evidence 레코드. "
        "오류 조건: repo/issue_number가 없는 경우, GitHub CLI(gh) 인증이 안 된 경우, "
        "이슈가 존재하지 않거나 이미 닫혀 있는 경우, 명령이 15초 안에 끝나지 않는 경우 — "
        "이 모든 경우 success=False와 error 메시지로 반환하며 예외를 던지지 않는다. "
        "승인 필요 여부: risk_level=medium이므로 원칙적으로 실행 전 사용자 승인이 "
        "필요하다. 다만 github.create_issue의 rollback 경로로 호출될 때는 이미 승인된 "
        "생성 작업 자체를 되돌리는 것이므로 별도의 새 승인을 요구하지 않는다 (SPEC §12.3 "
        "rollback 개념 — 롤백은 원래 승인의 취소이지 새로운 위험 행위가 아니다)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "repo": {
                "type": "string",
                "description": "이슈가 속한 저장소, 'owner/name' 형식 (필수)",
            },
            "issue_number": {
                "type": "integer",
                "description": "닫을 이슈 번호 (필수)",
            },
        },
        "required": ["repo", "issue_number"],
    }
    risk_level = "medium"
    required_scopes = {"github.write"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo", "")
        issue_number = arguments.get("issue_number", "")
        preview = f"GitHub 저장소 '{repo}'의 이슈 #{issue_number}를 닫을 예정"
        return ToolResult(success=True, data={"preview": preview}, metadata={"dry_run": True})

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        repo = arguments.get("repo")
        if not repo:
            return ToolResult(success=False, error="repo is required")
        issue_number = arguments.get("issue_number")
        if issue_number is None:
            return ToolResult(success=False, error="issue_number is required")
        try:
            issue_number = int(issue_number)
        except (TypeError, ValueError):
            return ToolResult(success=False, error="issue_number must be an integer")

        command = [
            "gh",
            "issue",
            "close",
            str(issue_number),
            "--repo",
            repo,
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
                success=False, error=f"gh issue close timed out after {_GH_TIMEOUT_SECONDS}s"
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"failed to run gh: {exc}")

        if proc.returncode != 0:
            return ToolResult(
                success=False, error=(proc.stderr or "gh issue close failed").strip()[:500]
            )

        evidence = [
            {
                "source_type": "github_issue",
                "source_id": f"{repo}#{issue_number}",
                "title": f"Issue #{issue_number} closed",
                "content": (proc.stdout or "").strip(),
                "metadata": {"repo": repo, "issue_number": issue_number},
            }
        ]
        return ToolResult(
            success=True,
            data={"issue_number": issue_number, "repo": repo},
            evidence=evidence,
        )

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        return result


default_tool_registry.register(GithubCreateIssueTool())
default_tool_registry.register(GithubCloseIssueTool())
