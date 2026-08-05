---
name: docker-status
version: 0.1.0
description: 이 머신에서 실행 중이거나 중지된 모든 Docker 컨테이너의 이름/이미지/상태를 온디맨드로 조회한다 (읽기 전용).
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - docker
  - infra
  - ops
---

# Purpose

사용자가 원할 때 직접 "지금 어떤 컨테이너가 떠있어?", "이 컨테이너 왜 죽었어?" 같은 질문에 답하기 위해
`docker.list_containers` Tool을 호출해 이 머신의 모든 Docker 컨테이너 상태를 조회한다. 자동으로 알림을
발생시키지 않는다 — 사용자가 명시적으로 이 Skill을 실행했을 때만 동작한다 (proactive assistant의
DockerHealthSource는 이상 상태가 감지된 컨테이너만 자동으로 알림을 보내는 별도 기능이며, 이 Skill과는
독립적이다).

# Trigger Conditions

- 사용자가 명시적으로 이 Skill을 실행 요청했을 때 (`pai skill run docker-status`, API
  `/api/v1/skills/docker-status/run`, 텔레그램 `/skill_run docker-status {}`).
- "컨테이너 상태 확인해줘", "지금 뭐 떠있어" 등 Docker 컨테이너 목록/상태를 묻는 대화에서 Orchestrator가
  자동으로 선택할 수도 있다.

# Preconditions

- 실행 환경에 `docker` CLI가 설치되어 있고 Docker 데몬이 응답해야 한다. 그렇지 않으면 Tool이 실패로
  응답한다 (아래 Failure Handling 참고).
- 입력 인자 없음 — 이 머신의 모든 컨테이너(다른 프로젝트 포함)를 대상으로 한다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `docker.list_containers` Tool 호출 1단계짜리 계획을 만든다.
2. `execute`: `DockerStatusTool().execute(arguments, tool_context)`를 호출한다. 반환된 컨테이너 개수로
   `"{n}개 컨테이너 확인됨"` 형태의 summary를 만들고, 각 컨테이너의 이름/상태 한 줄 요약을 evidence로 담는다.
3. `verify`: 컨테이너가 0개인 것은 정상 결과이지 실패가 아니므로 그대로 통과시킨다 — Tool 자체의
   success/error만으로 성패를 판단한다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않고 성공을 반환한다.

# Tool Policy

- 허용: `docker.list_containers` 단 하나. 컨테이너를 시작/중지/재시작/삭제하는 Tool은 존재하지 않으며
  이 Skill의 범위 밖이다.
- 금지: Shell 실행(Tool 내부의 `docker ps` 호출 제외), 파일 시스템 접근, 네트워크 접근.

# Evidence Requirements

- 각 컨테이너의 이름과 상태 문자열을 evidence에 담아, 사용자가 실제 `docker ps -a` 출력과 대조 검증할 수
  있게 한다.
- 컨테이너가 0개인 결과는 evidence가 비어 있어도 실패로 취급하지 않는다 (github-issues-lookup과 달리
  이 Skill은 evidence 존재를 성공 조건으로 강제하지 않는다 — verification.required: false).

# Failure Handling

- `docker` CLI가 설치되어 있지 않거나 Docker 데몬이 응답하지 않는 경우, 또는 명령이 15초 안에 끝나지
  않는 경우: Tool이 그 사실을 `error`에 담아 `success=False`로 반환한다 (빈 목록으로 위장하지 않는다,
  원인을 숨기지 않는다).

# Output Contract

`SkillResult`:
- `success`: Tool 호출이 성공했는지 여부 (컨테이너 0개는 성공으로 취급).
- `summary`: `"{n}개 컨테이너 확인됨"`, `"실행 중인 컨테이너 없음"`, 또는 실패 시 `"Docker 상태 조회 실패"`.
- `data`: `{"containers": [{"Names", "Image", "Status", "State", ...}, ...]}` — `docker ps -a --format
  '{{json .}}'`의 원본 필드를 그대로 보존한다 (`output.schema.json` 참고).
- `evidence`: 컨테이너별 이름/상태 한 줄 요약 목록.
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
