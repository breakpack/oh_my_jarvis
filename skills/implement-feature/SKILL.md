---
name: implement-feature
version: 0.1.0
description: 격리된 워크스페이스에서 패치를 적용하고(선택적으로 테스트까지 실행) diff와 테스트 결과를 반환한다. 커밋은 하지 않는다.
license: MIT
risk_level: medium
entrypoint: workflow.py
tags:
  - development
  - implement-feature
  - patch
---

# Purpose

사용자(또는 상위 계획 단계)가 이미 만든 unified diff 패치를, 실제 저장소가 아니라 격리된 Git worktree
워크스페이스에 적용해보고, 원하면 테스트까지 돌려서 결과를 diff와 함께 보고한다. "이 패치 적용해서 테스트
돌려봐" 같은 요청을 처리한다 — 어떤 경우에도 이 Skill 자체가 사용자의 실제 저장소를 커밋하지는 않는다.

# Trigger Conditions

- 사용자가 구체적인 patch(unified diff) 텍스트를 주고 저장소에 적용/검증해 달라고 요청할 때.
- 패치를 적용한 뒤 테스트까지 돌려서 통과 여부를 확인해 달라는 요청.
- 패치 텍스트 자체를 만들어달라는 요청(즉 "이 기능을 구현해줘, diff는 네가 짜")은 이 Skill의 범위가
  아니다 — 이 Skill은 이미 주어진 patch를 적용/검증하는 것까지만 담당한다.
- 실제 저장소에 즉시 commit/push 해달라는 요청은 이 Skill이 처리하지 않는다 — commit은 승인 이후 apps/api
  쪽에서 별도로 수행된다.

# Preconditions

- `source`: 대상 저장소의 절대 경로 (필수, `ALLOWED_REPOS`에 있어야 함).
- `patch`: 적용할 unified diff 텍스트 (필수).
- `test_command`: 패치 적용 후 실행할 명령 (`list[str]`, 선택). 첫 번째 원소가
  `personal_ai.development.workspace.ALLOWED_COMMANDS`
  (`pytest`/`ruff`/`mypy`/`python3`/`uv`/`npm`/`git`/`ls`/`cat`) 중 하나가 아니면 즉시 거부된다.
- risk_level이 `medium`이므로(SPEC §12.1) 이 Skill이 호출되기 전에 이미 상위 Policy Engine/Approval
  단계를 거쳤다고 가정한다 — 이 Skill 내부에서 별도의 승인 로직을 다시 구현하지 않는다. (패치 적용 자체는
  격리된 워크스페이스 안에서만 벌어지는, 언제든 폐기 가능한 행위이기 때문이다 — 실제로 되돌릴 수 없는
  행위인 commit만 별도 승인 게이트를 진짜로 거친다.)

# Workflow

1. `plan`: `create_workspace` → `apply_patch` → (test_command가 있으면) `run_command` → `get_diff` 순서의
   계획을 반환한다.
2. `execute`:
   a. `source`/`patch`가 없으면 즉시 실패 반환 (워크스페이스를 만들지 않는다).
   b. `create_workspace(source)`.
   c. `apply_patch(workspace_id, patch)` — `git apply --check` 후 실제 적용. 실패하면 워크스페이스를 바로
      정리(`destroy_workspace`)하고 실패를 반환한다 (성공한 것이 없으므로 남겨둘 이유가 없다).
   d. `test_command`가 있으면 `run_command(workspace_id, test_command)`. 명령이 allowlist에 없어
      `PermissionError`가 나면 워크스페이스를 정리하고 실패를 반환한다.
   e. `get_diff(workspace_id)`로 최종 diff를 가져온다.
   f. **워크스페이스를 destroy하지 않는다** — `rollback_token`에 `workspace_id`를 담아 반환한다. 패치가
      성공적으로 적용된 이상, 승인 흐름이 이 워크스페이스 안에서 직접 commit하거나(승인) 또는
      `rollback()`을 호출해 폐기할(거부) 기회를 준다.
3. `verify`: `execute` 결과를 그대로 승인한다.
4. `rollback`: `rollback_token`(workspace_id)으로 `destroy_workspace`를 호출해 워크스페이스를 완전히
   폐기한다 — 격리된 브랜치와 디렉터리이므로 원본 저장소에는 애초에 아무 흔적도 남지 않는다.

# Tool Policy

- 허용: `GitWorktreeRuntime`의 `create_workspace`/`apply_patch`/`run_command`/`get_diff`/`destroy_workspace`.
- **금지: `git add`, `git commit`, `git push` — 이 Skill의 코드 어디에도 존재하지 않는다.** 커밋은 별도
  승인 게이트를 통과한 뒤 apps/api 계층에서만 수행된다 (SPEC §9.1 "사용자 승인 전 commit 금지").
- 금지: `test_command`로 allowlist 밖의 명령을 실행하는 것 — `run_command`가 자체적으로 거부한다.

# Evidence Requirements

- `data.diff`가 실제로 적용된 변경사항의 근거다. `data.patch_result`(git apply의 성공 여부/stderr)와
  `data.test_result`(있는 경우 exit_code/stdout/stderr/duration_ms)도 함께 반환해 승인자가 무엇이
  일어났는지 재현 없이 확인할 수 있게 한다.

# Failure Handling

- `source` 또는 `patch`가 없으면: 워크스페이스를 만들지 않고 즉시 실패.
- `create_workspace` 실패(허용되지 않은 저장소 등): 원인을 `error`에 담아 반환.
- `apply_patch` 실패(패치가 저장소에 맞지 않음): 워크스페이스를 정리하고 실패 반환 — `data.patch_result`에
  `git apply`의 stderr가 담긴다.
- `test_command`가 allowlist에 없음: 워크스페이스를 정리하고 실패 반환.
- 패치는 적용됐지만 테스트가 실패(`exit_code != 0`): 이것은 "적용 실패"와 다르게 취급한다 — 패치는 이미
  적용되어 워크스페이스에 남아 있고(`rollback_token` 제공), `success=False`, `summary`에 실패한 테스트의
  exit code를 명시해 호출자가 diff와 테스트 결과를 보고 판단하게 한다.

# Output Contract

`SkillResult`:
- `success`: 패치가 적용되었고(있다면) 테스트가 통과했는지 여부.
- `summary`: `"Patch applied"` 또는 `"Patch applied; tests {passed|failed} (exit {n})"`.
- `data`: `{"workspace_id": str, "diff": str, "patch_result": {"success","stderr"},
  "test_result": {"exit_code","stdout","stderr","duration_ms"}|null}`.
- `rollback_token`: 패치가 성공적으로 적용된 경우 `workspace_id` (실패 시 `null`).
- `error`: 실패 시 원인, 성공 시 `null`.
