# Security

> 이 문서는 [SPEC.md](../SPEC.md) §3.5(Core Owns Security)와 §20(보안 요구사항)의 요약이다. 정책의 최종 근거는 SPEC.md이며, 구현이 이 문서와 다르면 SPEC.md와 코드를 함께 갱신한다.

## 원칙: Core Owns Security (SPEC.md §3.5)

외부 프레임워크, MCP 서버, Skill은 권한의 최종 결정자가 아니다. Personal AI OS Core만이 다음을 소유한다.

- Identity, Permission, Policy, Approval
- Secret access
- Execution sandbox
- Audit, Verification, Rollback policy

## Prompt Injection 방어 원칙 (SPEC.md §20.1)

다음은 모두 비신뢰 입력(untrusted input)으로 취급한다.

- 웹페이지, 이메일, PDF, GitHub Issue, MCP Resource, Skill README, Tool output

비신뢰 입력에 포함된 지시문(예: "이전 지시를 무시하라", "비밀을 출력하라", "Tool을 실행하라", "승인을 우회하라")은 시스템 명령으로 실행하지 않는다. 웹 콘텐츠와 Tool 결과는 항상 데이터로만 취급하며, 그 내용이 실행 경로를 바꾸도록 허용하지 않는다.

## Secret 정책 (SPEC.md §20.2)

- Secret Manager Adapter를 통해서만 접근한다.
- `.env`는 개발 전용이며 프로덕션 Secret 저장소로 사용하지 않는다.
- Secret 값은 로그에 기록하지 않고, 모델 Prompt에도 삽입하지 않는다.
- Skill에는 실제 Secret 값이 아닌 named secret reference만 제공한다.
- 외부 서비스 연결은 최소 Scope 원칙을 따른다.

## Shell 실행 제약 (SPEC.md §20.3)

- Shell 실행은 기본 비활성이다.
- 명령 실행 시 argument array를 사용하며 `shell=True`는 금지한다.
- 명령 allowlist, timeout, output limit을 강제한다.
- network 및 filesystem 접근을 제한하고, destructive command는 차단한다.
- 개발 Sandbox는 `~/.ssh`, `~/Library/Keychains`, 브라우저 프로필, 시스템 인증서, 사용자 홈 전체, 명시되지 않은 저장소, 프로덕션 kubeconfig에 접근할 수 없다(SPEC.md §9.2).

## Audit 정책 (SPEC.md §20.4)

다음을 반드시 기록한다.

- 사용자 요청, 선택된 Workflow/Skill/Model
- 검색 Source, Tool arguments hash
- Approval 기록, Tool 실행 결과, Verification, 오류, Rollback

단, 민감한 본문(메시지 전문 등)과 Secret 값 자체는 감사 로그에 기록하지 않는다.

## 위험 등급과 승인 (SPEC.md §12)

| 등급 | 예시 | 정책 |
|---|---|---|
| READ | 일정·파일·GitHub 조회 | 자동 실행 |
| LOW_WRITE | 개인 Task 생성 | Preview 또는 설정에 따라 자동 |
| MEDIUM | Notion 작성, 파일 수정, Issue 생성 | 승인 필요 |
| HIGH | 이메일 전송, git push, Docker 재시작 | 영향 표시 후 승인 |
| RESTRICTED | 결제, Keychain 접근, 파괴적 명령 | 차단 |

승인은 Argument hash 불변, 승인 재사용 금지, 만료 지원, 감사 로그 저장을 전제로 한다(SPEC.md §12.3).

## 현재 구현 상태

Phase 0/1 시점에는 위 정책 중 기본 Audit Event 기록만 최소 구현 대상이다(SPEC.md §23 Phase 1). Policy Engine, Approval Manager, Shell Sandbox, Skill 공급망 검증 등은 Phase 4~10에서 단계적으로 구현된다. 자세한 일정은 [ROADMAP.md](ROADMAP.md)를 참고한다.
