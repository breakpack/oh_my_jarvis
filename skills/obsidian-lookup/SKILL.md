---
name: obsidian-lookup
version: 0.1.0
description: 로컬 Obsidian 볼트에서 노트를 파일명/내용으로 검색하거나 특정 노트 전체를 읽는다.
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - obsidian
  - notes
  - knowledge
---

# Purpose

사용자가 자신의 Obsidian 볼트를 두 번째 뇌처럼 조회하려는 목적을 해결한다. "노트에서 X 찾아줘",
"그 회의록 노트 내용 보여줘" 같은 요청에 대해 `obsidian.search_notes` Tool을 호출해 실제 로컬
마크다운 파일을 검색하거나 읽어 반환한다. 이 Skill은 조회 전용이며 노트를 생성·수정·삭제하지 않는다.

# Trigger Conditions

- 사용자가 Obsidian 노트에서 특정 키워드/주제를 찾아달라고 요청할 때.
- 사용자가 특정 노트(파일 경로를 알고 있는 경우)의 전체 내용을 보여달라고 요청할 때.
- 노트를 새로 만들거나 수정하는 요청에는 이 Skill을 선택하지 않는다 (쓰기 작업은 범위 밖이며,
  현재 이 프로젝트에는 Obsidian 쓰기 Tool이 없다).

# Preconditions

- `OBSIDIAN_VAULT_PATH` 환경변수가 로컬 Obsidian 볼트의 절대 경로로 설정되어 있어야 한다.
  설정되어 있지 않으면 Tool이 그 사실을 error로 반환한다 (아래 Failure Handling 참고).
- `query`(검색) 또는 `path`(단일 노트 전체 조회) 중 하나는 있어야 한다.

# Workflow

1. `plan`: 입력 인자를 그대로 사용해 `obsidian.search_notes` Tool 호출 1단계짜리 계획을 만든다.
2. `execute`: `ObsidianSearchTool().execute(arguments, tool_context)`를 호출한다. `arguments`는
   가공 없이 그대로 전달한다. 반환된 노트 개수로 summary를 만들고, `success`/`data`/`evidence`/
   `error`를 그대로 SkillResult에 옮긴다.
3. `verify`: 일치하는 노트가 0개인 것은 정상 결과이지 실패가 아니므로 그대로 통과시킨다.
4. `rollback`: 읽기 전용이므로 아무 것도 되돌리지 않고 성공을 반환한다.

# Tool Policy

- 허용: `obsidian.search_notes` 단 하나. 노트 작성/수정/삭제 Tool은 존재하지 않으며 이 Skill의
  범위 밖이다.
- 금지: 볼트 밖 파일시스템 접근, 네트워크 접근, Shell 실행.

# Evidence Requirements

- 각 노트의 경로와 스니펫(또는 단일 노트 조회 시 전체 내용 앞부분)을 evidence에 담아, 사용자가
  실제 노트 파일과 대조 검증할 수 있게 한다.
- 검색 결과가 0개인 것은 evidence가 비어 있어도 실패로 취급하지 않는다
  (verification.required: false).

# Failure Handling

- `OBSIDIAN_VAULT_PATH`가 설정되지 않았거나 존재하지 않는 디렉터리인 경우: Tool이 그 사실을
  error에 담아 success=False로 반환한다.
- `path`가 볼트 밖 경로이거나(Path Traversal 시도 포함) 존재하지 않는 파일인 경우: Tool이
  success=False로 반환한다 (볼트 밖 접근은 Path.resolve() + relative_to() 기반으로 차단되며,
  파일시스템 접근을 시도하기 전에 걸러진다).
- `query`와 `path`가 둘 다 없는 경우: Tool이 즉시 success=False로 반환한다.

# Output Contract

`SkillResult`:
- `success`: Tool 호출이 성공했는지 여부 (검색 결과 0개는 성공으로 취급).
- `summary`: `"{n}개 노트 확인됨"` 또는 단일 노트 조회 시 `"노트 조회됨: {path}"` 형식의 1줄 요약.
- `data`: `{"notes": [{"path", "matched_by", "snippet"}, ...]}` (검색) 또는
  `{"notes": [{"path", "content"}]}` (단일 노트 조회) — `output.schema.json` 참고.
- `evidence`: 노트별 경로/스니펫 목록.
- `error`: 실패 시 원인 메시지, 성공 시 `null`.
