---
name: github-issue-create
version: 0.1.0
description: 사용자 승인을 받은 뒤 지정한 GitHub 저장소에 새 이슈를 생성한다.
license: MIT
risk_level: medium
entrypoint: workflow.py
tags:
  - github
  - issues
  - development
---

# Purpose

사용자가 GitHub 저장소에 새 이슈를 만들어 달라고 요청했을 때, 승인을 거쳐 `github.create_issue` Tool을
호출해 실제로 이슈를 생성한다. 이 Skill은 SPEC §12.1의 MEDIUM 위험 등급 예시("Issue 생성")를 실제로
동작하는 형태로 구현한 것으로, 승인(Approval) 흐름과 롤백(Rollback) 흐름을 함께 시연하는 데모 대상이다.

# Trigger Conditions

- 사용자가 "이슈 만들어줘", "버그 리포트 등록해줘"처럼 특정 저장소에 새 이슈 생성을 명시적으로 요청할 때.
- 저장소(`repo`)와 제목(`title`)이 사용자 요청 또는 대화 맥락에서 확정 가능할 때. 본문(`body`)은 선택이다.
- 이슈를 조회만 하려는 요청에는 이 Skill을 선택하지 않는다 — 그 경우 읽기 전용 `github-issues-lookup`
  Skill을 사용한다.

# Preconditions

- `repo`(owner/name 형식)와 `title`이 확정되어 있어야 한다. 확정할 수 없으면 실행 전에 사용자에게 묻는다.
- **실행 전 사용자 승인이 반드시 필요하다** (manifest.yaml `approval.required_before: [github.create_issue]`,
  risk_level=medium). Orchestrator/Approval Manager가 `preview`(생성될 이슈의 repo/title/body 요약)를 사용자에게
  보여주고 명시적 승인을 받은 뒤에만 `execute`가 호출되어야 한다.
- `github.create_issue`/`github.close_issue` Tool이 Tool Registry에 등록되어 있어야 하고, 실행 환경에
  GitHub CLI(`gh`)가 설치·인증(`gh auth login`)되어 있어야 한다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `github.create_issue` Tool 호출 1단계짜리 계획을 만든다.
   `[{"step": "call_tool", "tool": "github.create_issue", "arguments": arguments}]`
   이 계획은 Approval Manager가 사용자에게 보여줄 preview의 근거가 된다.
2. `execute`: (승인이 완료된 뒤에만 호출됨을 전제로) `GithubCreateIssueTool().execute(arguments,
   tool_context)`를 호출한다. 성공하면 반환된 이슈 번호로 `rollback_token`을
   `json.dumps({"repo": repo, "issue_number": number})` 형태로 만들어 SkillResult에 담는다 — 이 토큰이
   나중에 `rollback`이 어떤 이슈를 닫아야 하는지 아는 유일한 방법이다. `success`/`data`/`evidence`/`error`는
   Tool 결과를 그대로 옮긴다.
3. `verify`: Tool의 `execute()`가 이미 성공/실패를 정확히 판단해 반환하므로, 여기서 evidence 유무로
   success를 다시 뒤집지 않는다 (읽기 전용 Skill인 github-issues-lookup/local-file-search에서 evidence
   부재로 성공을 실패로 보정하는 것과 달리, 쓰기 작업은 "이슈가 실제로 생성됐는지"가 유일한 성공 기준이고
   그건 이미 execute() 단계에서 gh의 종료 코드와 출력 파싱으로 확정됐다). 결과를 그대로 반환한다.
4. `rollback`: `rollback_token`을 `json.loads`로 복원해 `repo`/`issue_number`를 얻고,
   `GithubCloseIssueTool().execute({"repo": repo, "issue_number": issue_number}, tool_context)`를 호출해
   방금 생성한 이슈를 닫는다. 이는 원래 승인받은 생성 작업 자체를 취소하는 것이므로 별도의 새 승인을
   요구하지 않는다 (SPEC §12.3).

# Tool Policy

- 허용: `github.create_issue`(생성), `github.close_issue`(오직 rollback 경로에서만 — 이 Skill이 방금 만든
  이슈를 되돌릴 때 사용). 그 외 이슈 코멘트/라벨/할당 등의 조작은 이 Skill의 범위 밖이며 호출하지 않는다.
- **`github.create_issue`는 승인 필요, 승인 없이 절대 호출 안 함.** manifest.yaml의
  `approval.required_before`에 명시되어 있고, 이 원칙은 Skill 코드가 아니라 Orchestrator/Approval Manager가
  Plan → Authorize 단계에서 강제한다 — `execute()`는 이미 승인된 계획을 실행하는 단계일 뿐, 그 자체로 승인
  여부를 판단하지 않는다.
- 금지: Shell 실행(subprocess는 Tool 내부에서 인자 리스트로만 `gh`를 호출하며 `shell=True`를 쓰지 않는다),
  이슈 삭제(GitHub API 자체가 이슈 삭제를 지원하지 않는다 — 닫기가 이 Skill이 제공하는 유일한 되돌리기
  수단이다).

# Evidence Requirements

- 생성 성공 시 evidence에는 최소한 새 이슈의 `source_id`(`repo#number`)와 `url`이 포함되어야 한다 — 사용자가
  실제로 생성된 이슈를 GitHub에서 확인할 수 있어야 한다 (SPEC §3.3 Evidence-first 원칙).
- 실패한 호출에는 evidence가 없다 — 이는 정상이며 `verify`가 이를 실패로 재해석하지 않는다(위 Workflow
  3번 참고). success 여부는 evidence 유무가 아니라 Tool의 실제 실행 결과로만 판단한다.

# Failure Handling

- 승인 없이 `execute`가 호출되는 상황은 이 Skill 자체가 아니라 Orchestrator/Approval Manager 레벨에서
  차단되어야 한다 — 이 Skill은 그 가정 위에서 동작한다.
- `gh` 인증 실패, 저장소 접근 권한 없음, 저장소 없음: Tool의 `error`를 그대로 `SkillResult.error`에 담아
  사용자에게 노출한다 (원인을 숨기지 않는다).
- 15초 서브프로세스 타임아웃: 재시도 없이 실패를 그대로 보고한다.
- `gh`가 예상한 이슈 URL 형식을 반환하지 않는 경우(예: 예상치 못한 CLI 출력 변경): "이슈 번호를 파싱하지
  못했다"는 명확한 오류로 보고한다 — 이슈가 실제로 생성됐을 수도 있으므로, 이 경우 사용자에게 저장소를
  직접 확인해보라고 안내해야 한다(이 Skill은 자동으로 재확인하지 않는다).
- 롤백 실행 자체가 실패하면(예: 이슈가 이미 닫혀 있음) `rollback`은 `success=False`와 원인을 그대로
  반환한다 — 롤백 실패를 성공으로 위장하지 않는다.

# Output Contract

`SkillResult`:
- `success`: 이슈 생성 성공 여부 (Tool의 실행 결과를 그대로 신뢰).
- `summary`: `"Created issue #{number} in {repo}"` 또는 `"Failed to create issue in {repo}"`.
- `data`: `{"number": int, "url": str}` — 생성된 이슈 정보 (`output.schema.json` 참고).
- `evidence`: 생성된 이슈를 가리키는 근거 목록.
- `rollback_token`: 성공 시 `json.dumps({"repo": str, "issue_number": int})` 형태의 문자열. 실패 시 `null`.
  `rollback()`은 이 토큰을 `json.loads`로 되돌려 `repo`/`issue_number`를 얻는다.
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
