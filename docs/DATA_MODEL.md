# Data Model

> 이 문서는 [SPEC.md](../SPEC.md) §14(데이터베이스)의 테이블 목록을 정리한 것이다. 각 테이블의 컬럼과 관계는 `migrations/`의 Alembic 마이그레이션과 SPEC.md §14를 최종 근거로 삼는다. 핵심 상태는 JSONB만으로 두지 말고 검색·무결성이 필요한 속성은 정규 컬럼으로 둔다(SPEC.md §14).

## Phase 0/1에서 실제 생성되는 테이블

Local Chat Vertical Slice(SPEC.md §23 Phase 1)와 기본 Audit 기록을 지원하기 위해 이 시점에 생성되는 테이블은 다음과 같다.

| 테이블 | 용도 |
|---|---|
| `users` | 사용자 계정 |
| `conversations` | 대화 세션 |
| `messages` | 대화 메시지 |
| `conversation_summaries` | 오래된 대화의 자동 요약 |
| `projects` | 프로젝트 단위 컨텍스트 |
| `audit_events` | Tool 실행, 요청, 오류 등 감사 기록 |

## 이후 Phase에서 추가되는 테이블

아래 테이블은 SPEC.md §14에 정의되어 있으나 Phase 0/1에서는 생성하지 않는다. 각 테이블이 필요해지는 시점은 대응하는 Phase(§23)를 따른다.

| 테이블 | 용도 | 관련 Phase |
|---|---|---|
| `project_events` | 프로젝트 상태 변경 이력 | Phase 2 |
| `tasks` | Task 생성·완료 | Phase 2 이후 (Skill/Approval 연동) |
| `decisions` | 프로젝트 결정 기록 | Phase 2 |
| `people` | 관계 모델의 사람 엔티티 | Phase 2~3 |
| `memories` | Profile/Preference/Decision 등 기억 | Phase 2 |
| `memory_embeddings` | 기억의 벡터 임베딩 | Phase 2~3 |
| `documents` | RAG 원본 문서 metadata | Phase 3 |
| `document_chunks` | 문서 청크 | Phase 3 |
| `document_embeddings` | 문서 청크의 벡터 임베딩 | Phase 3 |
| `entities` | 지식 그래프 엔티티 | Phase 3 |
| `relations` | 문서·대화·프로젝트·사람·결정 간 관계 | Phase 3 |
| `skills` | Skill 메타데이터 | Phase 4 |
| `skill_installations` | Skill 설치 상태 | Phase 4, 10 |
| `skill_versions` | Skill 버전 관리 | Phase 4, 10 |
| `tool_connections` | 외부 서비스 연결 | Phase 4 |
| `tool_executions` | Tool 실행 이력 | Phase 4~5 |
| `agent_runs` | Agent 실행 단위 | Phase 5, 8 |
| `approvals` | 승인 요청과 결과 | Phase 5 |
| `workspaces` | 개발 Workspace | Phase 6 |
| `workspace_runs` | Workspace 내 실행 이력 | Phase 6 |
| `workspace_artifacts` | Workspace 산출물 | Phase 6 |
| `notifications` | 능동적 알림 | Phase 9 |
| `scheduled_jobs` | 예약 작업/이벤트 폴링 | Phase 9 |

## 현재 구현 상태

이 문서 작성 시점 기준으로 Phase 0/1이 진행 중이며, 위 "Phase 0/1" 표의 테이블도 아직 마이그레이션이 적용되지 않았을 수 있다. 실제 스키마 상태는 `migrations/` 디렉터리와 `pai doctor`(SPEC.md §16)의 migration status 점검 결과를 항상 우선한다.
