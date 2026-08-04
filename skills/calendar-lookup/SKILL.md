---
name: calendar-lookup
version: 0.1.0
description: 지정한 기간의 캘린더 일정을 조회한다 (Stub — calendar.list_events Tool 미구현).
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - calendar
  - productivity
---

# Purpose

사용자가 자신의 캘린더에서 특정 기간의 일정을 확인하려는 목적을 해결한다. "이번 주 일정 알려줘",
"수요일 오후에 뭐 있어?" 같은 요청에 대해 (구현되면) `calendar.list_events` Tool을 호출해 실제 일정
목록을 가져와 요약한다. 이 Skill은 조회 전용이며 일정을 생성·수정·삭제하지 않는다.

# Trigger Conditions

- 사용자가 특정 날짜/기간의 일정 존재 여부, 목록, 충돌 여부를 물을 때.
- "이번 주", "다음 주 화요일", "오늘 오후" 등 시간 표현과 함께 캘린더 조회를 요청할 때.
- 일정을 새로 만들거나 초대를 보내는 요청에는 이 Skill을 선택하지 않는다 (쓰기 작업은 별도 Skill/Tool의
  몫이며 §5 Approval Manager를 거쳐야 한다).

# Preconditions

- 조회할 기간(`start`/`end` 또는 자연어 기간 표현을 정규화한 값)이 확정되어 있어야 한다.
- Calendar 서비스 연동(OAuth 토큰 등)이 Secret Manager Adapter를 통해 구성되어 있어야 한다.
- **현재 이 Skill은 Stub 상태다** — `calendar.list_events` Tool과 `workflow.py`가 아직 구현되지 않았다.
  Discover 단계(Skill Registry가 manifest.yaml + SKILL.md만으로 목록에 잡는 단계)에서는 정상적으로
  나타나지만, 실제 Plan/Execute를 시도하면 entrypoint 파일 부재로 실행이 실패한다.

# Workflow

(Phase 5+ 구현 예정) 실제 구현되면 다음 순서를 따른다:
1. `plan`: 입력 인자를 그대로 사용해 `calendar.list_events` Tool 호출 1단계짜리 계획을 만든다.
2. `execute`: `CalendarTool().execute(arguments, tool_context)`를 호출하고, 반환된 일정 개수로 요약을
   만들어 SkillResult로 변환한다 (github-issues-lookup Skill과 동일한 패턴).
3. `verify`: evidence(일정 ID/URL 등)가 비어 있지 않은지 확인한다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않는다.

# Tool Policy

- 허용 예정: `calendar.list_events` 단 하나 (읽기 전용).
- 금지: 일정 생성/수정/삭제, 초대 발송 — 이런 쓰기 작업은 별도의 승인이 필요한 Skill/Tool로 분리한다.

# Evidence Requirements

- 각 일정 항목은 최소한 일정 제목, 시작/종료 시각, 원본 캘린더 링크(또는 ID)를 근거로 포함해야 한다.

# Failure Handling

**현재 Calendar 연동이 설정되지 않음 — Phase 5+에서 구현 예정.** 이 Skill을 지금 실행하려 하면 다음과 같이
동작해야 한다 (Resolver/Executor가 처리):
- `calendar.list_events` Tool이 Tool Registry에 없으므로 Tool 조회 단계에서 실패하고, 사용자에게 "Calendar
  연동이 아직 준비되지 않았습니다"라는 명확한 오류를 보여준다 (SPEC §25 DoD "사용자에게 실패 원인 표시" —
  실패를 숨기거나 조용히 무시하지 않는다).
- 이 상태를 성공으로 위장하거나 빈 목록을 "일정 없음"으로 잘못 보고하지 않는다 — 미구현과 "일정 0건"은
  다른 상태이므로 구분해서 오류를 표시한다.

# Output Contract

(Phase 5+ 구현 예정) 구현되면 github-issues-lookup Skill과 동일한 형태의 `SkillResult`를 반환한다:
`success`, `summary`(`"Found {event_count} events between {start} and {end}"`), `data.events`, `evidence`,
`error`.
