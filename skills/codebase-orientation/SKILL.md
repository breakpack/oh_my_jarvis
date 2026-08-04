---
name: codebase-orientation
version: 0.1.0
description: 지정한 저장소를 격리된 워크스페이스에서 훑어보고 구조 요약(주요 디렉터리, README 발췌)을 반환한다.
license: MIT
risk_level: read
entrypoint: workflow.py
tags:
  - development
  - codebase
  - orientation
---

# Purpose

사용자가 (자신의 것이든, 처음 보는 것이든) 어떤 저장소를 처음 살펴볼 때 "이 저장소가 대충 뭘로 이루어져
있는지"를 빠르게 요약해준다. "이 프로젝트 구조 좀 설명해줘", "이 저장소에 뭐가 있어?" 같은 요청을
`GitWorktreeRuntime` 기반의 격리된 워크스페이스에서 처리한다 — 사용자의 실제 작업 디렉터리나 셸을 건드리지
않는다.

# Trigger Conditions

- 사용자가 특정 Git 저장소 경로를 주고 "구조를 알려줘", "뭐가 들어있어", "처음 보는 코드인데 오리엔테이션
  해줘" 같은 요청을 할 때.
- 코드를 실제로 수정하거나 커밋해야 하는 요청은 이 Skill의 범위가 아니다 (`implement-feature` 참고) — 이
  Skill은 읽기 전용이다.

# Preconditions

- `source`: 대상 저장소의 절대 경로 (필수). `personal_ai.development.workspace.ALLOWED_REPOS`에 명시적으로
  포함된 저장소만 허용된다 — 목록에 없는 저장소는 `create_workspace`가 `PermissionError`로 즉시 거부한다
  (SPEC §9.2 "명시되지 않은 저장소" 금지).
- 대상 저장소는 유효한 Git 저장소여야 한다 (`git worktree add`가 성립해야 함).

# Workflow

1. `plan`: 아래 단계를 순서대로 나열한 계획을 반환한다 (실제 실행 순서와 동일).
2. `execute`:
   a. `GitWorktreeRuntime().create_workspace(source)` — 격리된 워크스페이스(브랜치
      `workspace/<uuid>`)를 생성한다.
   b. `search(workspace_id, "")` — 빈 검색어는 모든 파일명과 매치되므로, 저장소 전체에서 파일 경로를
      최대 50개(Search cap) 샘플링해 "구조"의 대리 지표로 쓴다. 경로의 첫 세그먼트를 모아 최상위
      디렉터리/파일 목록을 만든다.
   c. `search(workspace_id, "README")` — README류 파일을 찾는다.
   d. README를 찾았으면 `read_file`로 내용을 읽어 앞 400자를 발췌한다.
   e. `destroy_workspace(workspace_id)` — 성공/실패 여부와 무관하게 항상 호출한다(`finally`).
3. `verify`: `execute`의 결과를 그대로 승인한다 (추가로 되돌릴 부작용이 없다).
4. `rollback`: 아무 것도 하지 않는다 — 워크스페이스는 `execute` 종료 시 이미 정리되었다.

# Tool Policy

- 허용: `GitWorktreeRuntime`의 `create_workspace`/`search`/`read_file`/`destroy_workspace` 뿐. `apply_patch`,
  `run_command`, `get_diff`는 호출하지 않는다 — 이 Skill은 아무것도 바꾸지 않는다.
- 금지: Shell 직접 실행, 워크스페이스 외부 경로 접근 (Path traversal은 `GitWorktreeRuntime.read_file`이
  차단한다).

# Evidence Requirements

- `evidence`에는 샘플링된 파일 중 최대 10개의 경로를 담아, 요약이 실제로 어떤 파일들을 근거로 했는지
  추적할 수 있게 한다 (SPEC §3.3 Evidence-first).

# Failure Handling

- `source`가 없으면 즉시 `success=False`로 반환한다 (워크스페이스를 만들지 않는다).
- `create_workspace`가 실패하면(허용되지 않은 저장소, 잘못된 Git 저장소 등) 그 원인을 `error`에 그대로
  담아 반환한다.
- README를 찾지 못해도 실패가 아니다 — `readme_path`/`readme_excerpt`가 `null`인 채로 나머지 구조 요약만
  반환한다.
- `execute` 도중 어떤 예외가 나더라도 워크스페이스 정리(`destroy_workspace`)는 `finally`로 보장된다.

# Output Contract

`SkillResult`:
- `success`: 워크스페이스 생성과 탐색이 정상적으로 끝났는지 여부.
- `summary`: `"{N} file(s) sampled across {M} top-level entries: {...}. README (...): {발췌}"` 형식의 1~2문장
  요약.
- `data`: `{"top_level_entries": [...], "file_sample": [{"path","matched_by"}, ...], "readme_path": str|null,
  "readme_excerpt": str|null}`.
- `evidence`: 샘플 파일 경로 목록(최대 10개).
- `error`: 실패 시 원인, 성공 시 `null`.
