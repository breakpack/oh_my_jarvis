---
name: local-file-search
version: 0.1.0
description: 로컬 디렉터리 하위에서 파일명 또는 내용이 검색어와 일치하는 파일을 찾는다.
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - files
  - search
  - development
---

# Purpose

사용자가 로컬 파일 시스템에서 특정 파일이나 코드/텍스트 조각을 찾고 싶을 때 이 Skill을 사용한다.
"이 프로젝트에서 config 파일 어디 있어?", "TODO 라는 문자열이 들어간 파일 찾아줘" 같은 요청을
`files.search` Tool 호출로 처리해 일치하는 파일 경로와 스니펫을 반환한다. 파일을 읽거나 수정하지는
않는다 — 위치를 찾아주는 것까지가 이 Skill의 책임이다.

# Trigger Conditions

- 사용자가 파일명 패턴(예: `*.env`, `config.yaml`) 또는 파일 내용 검색어를 언급하며 "찾아줘", "어디 있어",
  "검색해줘" 라고 요청할 때.
- 검색 범위가 되는 디렉터리(활성 프로젝트 워크스페이스 등)를 특정할 수 있을 때.
- 파일을 열어서 내용을 요약/수정해야 하는 요청은 이 Skill의 범위를 넘어서므로 선택하지 않는다 (검색까지만
  담당).

# Preconditions

- `query`(검색어)가 필요하다. `root`는 선택 인자이며 생략하면 워크스페이스 루트(`WORKSPACE_ROOT` 환경변수,
  없으면 현재 작업 디렉터리) 전체를 검색한다.
- `root`는 절대 경로가 아니라 워크스페이스 루트 기준 **상대 경로**다. Tool이 경로를 워크스페이스 루트 기준으로
  resolve한 뒤 그 범위를 벗어나는지 검사하므로(symlink·`..` 등 우회 시도 포함), 워크스페이스 밖을 가리키는
  `root`는 Tool 자체가 거부한다 — 이 Skill이 별도로 경로를 검증할 필요는 없다 (AGENTS.md "사용자 홈 전체
  접근 금지" 원칙을 Tool 레벨에서 강제).
- `files.search` Tool이 Tool Registry에 등록되어 있어야 한다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `files.search` Tool 호출 1단계짜리 계획을 만든다.
   `[{"step": "call_tool", "tool": "files.search", "arguments": arguments}]`
2. `execute`: `LocalFileSearchTool().execute(arguments, tool_context)`를 호출한다. `query`/`root`는 가공
   없이 그대로 전달한다. Tool 결과의 `data.matches` 개수를 세어 `"Found {n} matches for '{query}' under
   {root}"` 형태의 summary를 만들고, `success`/`data`/`evidence`/`error`를 그대로 SkillResult에 옮긴다.
3. `verify`: evidence가 비어 있지 않으면 결과를 그대로 승인한다. evidence가 비어 있으면 `success=False`로
   보정한다 — "찾았다"고 주장하면서 근거 파일 경로가 하나도 없는 결과를 사용자에게 그대로 전달하지 않는다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않고 성공을 반환한다.

# Tool Policy

- 허용: `files.search` 단 하나. 파일 읽기/쓰기/삭제, Shell 명령 실행은 이 Skill의 범위 밖이며 호출하지
  않는다.
- 금지: 워크스페이스 루트 밖의 경로 접근(Path traversal), Shell 실행을 통한 검색(`find`/`grep` 직접 실행
  금지 — Tool을 거쳐야 한다).

# Evidence Requirements

- 각 일치 항목은 Tool이 반환한 `evidence`에 최소한 파일 경로와, 파일명/내용 중 무엇으로 일치했는지
  (`matched_by`)를 포함해야 한다 — 사용자가 실제 파일에서 검증할 수 있어야 한다 (SPEC §3.3 Evidence-first
  원칙). 줄 번호·스니펫까지는 이 Tool의 현재 구현 범위 밖이다.
- evidence가 없는 결과는 `verify` 단계에서 실패로 취급한다.

# Failure Handling

- `root`가 워크스페이스 루트를 벗어나거나(Path traversal), 존재하지 않거나 디렉터리가 아닐 때: Tool의
  `error`를 그대로 `SkillResult.error`에 담아 사용자에게 노출한다.
- 검색 결과가 0건일 때: 이는 오류가 아니다 — `success=True`, `summary="Found 0 matches ..."`로 정상
  보고한다 (다만 evidence가 비어 있으므로 `verify` 단계 규칙에 따라 최종 success는 False로 보정된다 — 이
  Skill은 "결과 없음"과 "실패"를 SkillResult 레벨에서 구분하지 않고 근거 없는 성공을 허용하지 않는 원칙을
  일관되게 적용한다).
- 검색 범위가 너무 넓어 타임아웃(runtime.timeout_seconds=30 초과)이 발생하면 실패로 보고하고, summary에
  범위를 좁혀 재시도하라는 안내를 포함한다.

# Output Contract

`SkillResult`:
- `success`: Tool 호출과 evidence 검증이 모두 성공했는지 여부.
- `summary`: `"Found {match_count} matches for '{query}' under {root}"` 형식의 1줄 요약.
- `data`: `{"matches": [{"path", "matched_by"}, ...]}` — Tool이 반환한 원본 구조를 그대로 보존한다
  (`path`는 워크스페이스 루트 기준 상대 경로, `matched_by`는 `filename` 또는 `content`; `output.schema.json`
  참고).
- `evidence`: 각 일치 파일을 가리키는 근거 목록(경로 등).
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
