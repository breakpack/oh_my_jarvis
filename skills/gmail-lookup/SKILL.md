---
name: gmail-lookup
version: 0.1.0
description: Gmail 검색 문법으로 받은편지함을 조회해 제목/발신자/날짜/미리보기를 반환한다.
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - gmail
  - email
  - inbox
---

# Purpose

사용자가 자신의 Gmail 받은편지함 현황을 확인하려는 목적을 해결한다. "안 읽은 메일 있어?",
"누구한테 온 메일 찾아줘" 같은 요청에 대해 `gmail.search_messages` Tool을 호출해 실제 메일
목록을 가져와 요약한다. 이 Skill은 조회 전용이며 메일을 발송·삭제·라벨 변경하지 않는다.

# Trigger Conditions

- 사용자가 Gmail 검색어(발신자, 읽음 여부, 날짜 범위 등)와 함께 메일 조회를 요청할 때.
- "안 읽은 메일", "오늘 온 메일", "누구한테 온 메일" 등 메일 존재/개수/내용을 묻는 표현이 있을 때.
- 메일을 새로 보내거나 삭제/라벨 변경하는 요청에는 이 Skill을 선택하지 않는다 (쓰기 작업은
  범위 밖이며, 현재 이 프로젝트에는 Gmail 쓰기 Tool이 없다).

# Preconditions

- `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` 환경변수가 Google OAuth
  자격증명으로 설정되어 있어야 한다 (Google Cloud Console에서 OAuth 클라이언트를 만들고
  `gmail.readonly` 스코프로 리프레시 토큰을 발급받아야 함). 설정되어 있지 않으면 Tool이 그 사실을
  error로 반환한다 (아래 Failure Handling 참고).
- `query` 인자(Gmail 검색 문법)가 확정되어 있어야 한다.
- 네트워크 접근이 허용된 환경(runtime.network_access: allowlist)에서만 실행 가능하다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `gmail.search_messages` Tool 호출 1단계짜리 계획을 만든다.
2. `execute`: `GmailSearchTool().execute(arguments, tool_context)`를 호출한다. Tool은 내부적으로
   리프레시 토큰을 액세스 토큰으로 교환한 뒤 Gmail API를 호출한다. 반환된 메일 개수로 summary를
   만들고, `success`/`data`/`evidence`/`error`를 그대로 SkillResult에 옮긴다.
3. `verify`: 검색 결과가 0개인 것은 정상 결과이지 실패가 아니므로 그대로 통과시킨다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않고 성공을 반환한다.

# Tool Policy

- 허용: `gmail.search_messages` 단 하나 (gmail.readonly 스코프). 메일 발송/삭제/라벨 변경 Tool은
  존재하지 않으며 이 Skill의 범위 밖이다.
- 금지: Shell 실행, 파일 시스템 접근, Gmail 외 다른 외부 서비스 Tool 호출.

# Evidence Requirements

- 각 메일의 제목/발신자/날짜/미리보기를 evidence에 담아, 사용자가 실제 Gmail에서 대조 검증할 수
  있게 한다.
- 검색 결과가 0개인 것은 evidence가 비어 있어도 실패로 취급하지 않는다
  (verification.required: false).

# Failure Handling

- OAuth 자격증명이 설정되지 않은 경우: Tool이 즉시 error로 안내 메시지를 반환한다 (네트워크
  호출을 시도하지 않는다).
- 리프레시 토큰이 만료/취소되어 액세스 토큰 교환이 실패하는 경우, 또는 Gmail API가 오류를
  반환하는 경우: Tool이 해당 HTTP 상태 코드와 응답 본문 일부를 error에 담아 success=False로
  반환한다 (원인을 숨기지 않는다).
- 요청이 15초 안에 끝나지 않는 경우: Tool이 그 사실을 error에 담아 반환한다.

# Output Contract

`SkillResult`:
- `success`: OAuth 토큰 교환과 Gmail API 호출이 모두 성공했는지 여부 (검색 결과 0개는 성공).
- `summary`: `"{n}개 메일 확인됨"` 형식의 1줄 요약.
- `data`: `{"messages": [{"id", "subject", "from", "date", "snippet"}, ...]}` — `output.schema.json`
  참고.
- `evidence`: 메일별 제목/발신자/날짜/미리보기 목록.
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
