"""Docker container status tool — read-only, on-demand (SPEC.md §7, §20.3)."""

from __future__ import annotations

import json
import subprocess

from personal_ai.tools.base import ToolContext, ToolResult
from personal_ai.tools.registry import default_tool_registry

_DOCKER_TIMEOUT_SECONDS = 15


class DockerStatusTool:
    name = "docker.list_containers"
    description = (
        "목적: 이 머신에서 실행 중이거나 중지된 모든 Docker 컨테이너의 이름/이미지/상태를 "
        "조회한다. "
        "언제 사용: 사용자가 '컨테이너 상태 확인해줘', '지금 뭐 떠있어', '이 컨테이너 왜 죽었어' "
        "등 현재 Docker 컨테이너 목록/상태를 물을 때 사용한다. "
        "언제 사용하면 안 되는지: 컨테이너를 시작/중지/재시작/삭제하는 용도로는 사용할 수 없다 "
        "(본 Tool은 조회 전용이며 그런 쓰기 동작을 수행하지 않는다). "
        "입력 의미: 입력 인자 없음 — 이 머신의 모든 컨테이너를 대상으로 한다. "
        "외부 영향: 없음 — `docker ps -a`만 실행하며 어떤 컨테이너 상태도 변경하지 않는다. "
        "반환값: data.containers에 각 컨테이너의 Names/Image/Status/State 등 `docker ps` "
        "원본 필드가 담긴 리스트. 컨테이너가 0개인 것은 실패가 아니라 정상 결과다. "
        "오류 조건: docker CLI가 설치되어 있지 않거나 Docker 데몬이 응답하지 않는 경우, "
        "명령이 15초 안에 끝나지 않는 경우 — 이 모든 경우 success=False와 error 메시지로 "
        "반환하며 예외를 던지지 않는다. "
        "승인 필요 여부: risk_level=read이므로 SPEC §12.1에 따라 자동 실행 가능 — 승인 불필요."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    risk_level = "read"
    required_scopes = {"docker.read"}

    async def dry_run(self, arguments: dict, context: ToolContext) -> ToolResult:
        return ToolResult(
            success=True,
            data={"preview": "이 머신의 모든 Docker 컨테이너 상태 조회 예정"},
            metadata={"dry_run": True},
        )

    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult:
        command = ["docker", "ps", "-a", "--format", "{{json .}}"]
        try:
            proc = subprocess.run(  # noqa: S603 — argument list, shell=False, timeout set
                command,
                capture_output=True,
                text=True,
                timeout=_DOCKER_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False, error=f"docker ps timed out after {_DOCKER_TIMEOUT_SECONDS}s"
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"failed to run docker: {exc}")

        if proc.returncode != 0:
            return ToolResult(
                success=False, error=(proc.stderr or "docker ps failed").strip()[:500]
            )

        containers: list[dict] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return ToolResult(success=True, data={"containers": containers})

    async def verify(self, result: ToolResult, context: ToolContext) -> ToolResult:
        # An empty container list is a valid outcome (nothing running), not a failure.
        return result


default_tool_registry.register(DockerStatusTool())
