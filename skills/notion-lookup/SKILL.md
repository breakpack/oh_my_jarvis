---
name: notion-lookup
version: 0.1.0
description: Notion 워크스페이스에서 페이지/데이터베이스 항목을 검색한다 (Stub — notion.search_pages Tool 미구현).
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - notion
  - knowledge
---

# Purpose

사용자가 자신의 Notion 워크스페이스에서 페이지나 데이터베이스 항목을 찾으려는 목적을 해결한다.
"Notion에서 K8s 보안 부채 문서 찾아줘", "프로젝트 노트 어디 있어?" 같은 요청에 대해 (구현되면)
`notion.search_pages` Tool을 호출해 실제 검색 결과를 가져와 요약한다. 이 Skill은 조회 전용이며 Notion
페이지를 생성·수정·삭제하지 않는다.

# Trigger Conditions

- 사용자가 Notion에 저장된 문서/노트/데이터베이스 항목을 검색어와 함께 찾아달라고 요청할 때.
- "Notion에서", "노트에" 같은 표현으로 검색 대상을 Notion으로 명시했을 때.
- 새 Notion 페이지 생성이나 기존 페이지 수정 요청에는 이 Skill을 선택하지 않는다 (쓰기 작업은 별도
  Skill/Tool이며 §5 Approval Manager를 거쳐야 한다).

# Preconditions

- 검색어(`query`)와, 필요하다면 검색 범위(특정 데이터베이스/워크스페이스)가 확정되어 있어야 한다.
- Notion 연동(API 토큰)이 Secret Manager Adapter를 통해 구성되어 있어야 한다.
- **현재 이 Skill은 Stub 상태다** — `notion.search_pages` Tool과 `workflow.py`가 아직 구현되지 않았다.
  Discover 단계(Skill Registry가 manifest.yaml + SKILL.md만으로 목록에 잡는 단계)에서는 정상적으로
  나타나지만, 실제 Plan/Execute를 시도하면 entrypoint 파일 부재로 실행이 실패한다.

# Workflow

(Phase 5+ 구현 예정) 실제 구현되면 다음 순서를 따른다:
1. `plan`: 입력 인자를 그대로 사용해 `notion.search_pages` Tool 호출 1단계짜리 계획을 만든다.
2. `execute`: `NotionSearchTool().execute(arguments, tool_context)`를 호출하고, 반환된 페이지 개수로
   요약을 만들어 SkillResult로 변환한다 (github-issues-lookup Skill과 동일한 패턴).
3. `verify`: evidence(페이지 URL/ID 등)가 비어 있지 않은지 확인한다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않는다.

# Tool Policy

- 허용 예정: `notion.search_pages` 단 하나 (읽기 전용).
- 금지: 페이지 생성/수정/삭제 — 이런 쓰기 작업(예: SPEC §6.4 예시의 `notion.create_page`)은 별도의 승인이
  필요한 Skill/Tool로 분리한다.

# Evidence Requirements

- 각 검색 결과 항목은 최소한 페이지 제목과 Notion 페이지 링크(또는 ID)를 근거로 포함해야 한다.

# Failure Handling

**현재 Notion 연동이 설정되지 않음 — Phase 5+에서 구현 예정.** 이 Skill을 지금 실행하려 하면 다음과 같이
동작해야 한다 (Resolver/Executor가 처리):
- `notion.search_pages` Tool이 Tool Registry에 없으므로 Tool 조회 단계에서 실패하고, 사용자에게 "Notion
  연동이 아직 준비되지 않았습니다"라는 명확한 오류를 보여준다 (SPEC §25 DoD "사용자에게 실패 원인 표시" —
  실패를 숨기거나 조용히 무시하지 않는다).
- 이 상태를 성공으로 위장하거나 빈 목록을 "결과 없음"으로 잘못 보고하지 않는다 — 미구현과 "검색 결과 0건"은
  다른 상태이므로 구분해서 오류를 표시한다.

# Output Contract

(Phase 5+ 구현 예정) 구현되면 github-issues-lookup Skill과 동일한 형태의 `SkillResult`를 반환한다:
`success`, `summary`(`"Found {page_count} pages matching '{query}'"`), `data.pages`, `evidence`, `error`.
