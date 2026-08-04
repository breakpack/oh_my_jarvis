---
name: github-issues-lookup
version: 0.1.0
description: 지정한 GitHub 저장소의 이슈 목록을 상태(open/closed/all)와 개수 제한 조건으로 조회한다.
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - github
  - issues
  - development
---

# Purpose

사용자가 특정 GitHub 저장소의 이슈 현황을 확인하려는 목적을 해결한다. "이 저장소에 열려있는 이슈 알려줘",
"버그 라벨 이슈 몇 개나 밀려있어?" 같은 요청에 대해 `github.list_issues` Tool을 호출해 실제 이슈 목록을
가져와 요약한다. 이 Skill 자체는 이슈를 생성·수정·닫지 않는다 — 조회 전용이다.

# Trigger Conditions

- 사용자가 GitHub 저장소 이름(owner/repo 형식 또는 자연어로 식별 가능한 저장소)과 함께 이슈 조회를 요청할 때.
- "오픈 이슈", "최근 이슈", "버그 목록", "이슈 몇 개" 등 이슈 존재/개수/상태를 묻는 표현이 있을 때.
- 이슈를 새로 만들거나 코멘트를 다는 요청에는 이 Skill을 선택하지 않는다 (쓰기 작업은 별도 Skill/Tool의 몫).

# Preconditions

- `repo` 인자(owner/repo 형식)가 사용자 요청 또는 활성 프로젝트 설정에서 확정되어 있어야 한다. 확정할 수
  없으면 실행 전에 사용자에게 저장소를 물어본다.
- `github.list_issues` Tool이 Tool Registry에 등록되어 있어야 한다. 이 Tool은 내부적으로 GitHub CLI(`gh`)의
  `gh issue list` 서브프로세스를 호출하므로, 실행 환경에 `gh`가 설치되어 있고 `gh auth login`으로 인증되어
  있어야 한다. 인증이 없으면 Tool 호출이 실패하고 이 Skill은 그 실패를 그대로 보고한다 (아래 Failure
  Handling 참고).
- 네트워크 접근이 허용된 환경(runtime.network_access: allowlist)에서만 실행 가능하다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `github.list_issues` Tool 호출 1단계짜리 계획을 만든다.
   `[{"step": "call_tool", "tool": "github.list_issues", "arguments": arguments}]`
2. `execute`: `GithubIssuesTool().execute(arguments, tool_context)`를 호출한다. `arguments`는 가공 없이
   그대로 전달한다 (repo/state/limit 검증은 Tool과 input_schema가 담당). Tool 결과의 `data.issues` 개수를
   세어 `"Found {n} issues in {repo}"` 형태의 summary를 만들고, `success`/`data`/`evidence`/`error`를
   그대로 SkillResult에 옮긴다.
3. `verify`: evidence가 비어 있지 않으면 결과를 그대로 승인한다. evidence가 비어 있으면(Tool이 근거 없이
   성공을 주장한 경우) `success=False`로 보정해, 근거 없는 성공 보고가 사용자에게 전달되지 않게 한다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않고 성공을 반환한다.

# Tool Policy

- 허용: `github.list_issues` 단 하나. 이슈 조회 이상의 권한(이슈 작성/수정/닫기, PR 조작 등)은 이 Skill의
  범위 밖이며 호출하지 않는다.
- 금지: Shell 실행, 파일 시스템 접근, 다른 외부 서비스 Tool 호출.

# Evidence Requirements

- 각 이슈 항목은 Tool이 반환한 `evidence`에 최소한 이슈 번호와 URL을 포함해야 한다 (사용자가 실제 GitHub
  페이지에서 검증할 수 있어야 함 — SPEC §3.3 Evidence-first 원칙).
- evidence가 없는 결과는 `verify` 단계에서 실패로 취급한다.

# Failure Handling

- `gh` CLI가 설치되어 있지 않거나 인증되지 않은 경우: `gh issue list`가 0이 아닌 종료 코드로 끝나고, Tool은
  그 stderr를 `error`에 담아 반환한다 — 이 Skill은 그 메시지를 그대로 `SkillResult.error`에 옮긴다 (원인을
  숨기지 않는다).
- 저장소가 존재하지 않거나 접근 불가(404/403 상당의 `gh` 오류): Tool의 error를 그대로 전달하고
  `success=False`로 보고한다.
- Tool 자체의 15초 서브프로세스 타임아웃(`gh issue list` 명령이 끝나지 않는 경우): Tool이 타임아웃 오류를
  반환하며, 이 Skill은 재시도 없이 실패를 그대로 보고한다 — 재시도는 호출자(Orchestrator)의 정책에 맡긴다.
- `repo` 형식이 잘못됐거나(`state`가 open/closed/all 외 값) `limit`이 정수가 아닌 경우: Tool이 입력 검증
  단계에서 바로 실패를 반환한다.

# Output Contract

`SkillResult`:
- `success`: Tool 호출과 evidence 검증이 모두 성공했는지 여부.
- `summary`: `"Found {issue_count} issues in {repo}"` 형식의 1줄 요약.
- `data`: `{"issues": [{"number", "title", "state", "url", ...}, ...]}` — Tool이 반환한 원본 구조를 그대로
  보존한다 (`output.schema.json` 참고).
- `evidence`: 각 이슈를 가리키는 근거 목록(번호, URL 등).
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
