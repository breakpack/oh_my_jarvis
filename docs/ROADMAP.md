# Roadmap

> 이 문서는 [SPEC.md](../SPEC.md) §23(구현 Roadmap)을 표로 정리한 것이다. 각 Phase의 상세 구현 항목과 완료 조건은 SPEC.md §23을 최종 근거로 삼는다.

## 현재 상태

- **Phase 0 ~ Phase 8: 완료** (`feat/phase-0` ~ `feat/phase-8` 브랜치)
- **Phase 9 ~ Phase 10: 계획됨** — 각 Phase는 동일한 방식(오케스트레이션 병렬 개발 + `feat/phase-N` 브랜치)으로 이어서 진행한다.

## Phase 목록

| Phase | 이름 | 핵심 구현 항목 | 상태 |
|---|---|---|---|
| 0 | Repository Bootstrap | Monorepo, FastAPI, Next.js, CLI, PostgreSQL+pgvector, Redis, Alembic, OpenTelemetry 기본, Makefile, CI, AGENTS.md | 완료 |
| 1 | Local Chat Vertical Slice | Conversation/Message, Ollama Provider, SSE Streaming, Chat UI, CLI Chat, Local/Cloud 수동 선택, 기본 Audit | 완료 |
| 2 | Project and Memory | Project CRUD, Active Project, Memory CRUD, Conversation Summary, Explicit remember/forget, Memory policy | 완료 |
| 3 | Second Brain RAG | Native parser(pypdf, Docling은 교체 가능한 어댑터로 계획만), Chunking, Local embedding(bge-m3), Hybrid retrieval, Evidence UI, Knowledge CLI | 완료 |
| 4 | Skill SDK and Read-only Tools | Skill manifest, SKILL.md loader, Schema validation, Skill Registry/Resolver, MCP Adapter(실제 stdio 연동), github-issues-lookup/local-file-search Skill, calendar/notion Stub, Skill CLI | 완료 |
| 5 | Approval and Mutation | Policy Engine, Approval Manager(Argument hash 검증), Task CRUD(LOW_WRITE 자동), GitHub Issue 생성(MEDIUM, 승인+Rollback), Calendar/Notion/Email은 Phase4 Stub 유지 | 완료 |
| 6 | Development Agent | Workspace(git worktree Sandbox), Repository search/read, Patch, 명령 allowlist 기반 Test 실행, Diff, 승인 게이트된 Commit, Workspace escape 테스트. OpenHands Adapter 평가는 보류(문서화 예정) | 완료 |
| 7 | Browser Agent | Playwright Tool(실제 Chromium), 세션 격리, web-read/web-form-submit Skill(폼 제출 승인 게이트), Prompt injection 방어+테스트. Browser Use는 Docling과 동일하게 어댑터 자리만 마련 | 완료 |
| 8 | Durable Workflow | LangGraph + PostgreSQL Checkpoint(실제 서버 재시작 복구 검증됨), Interrupt/Resume, tool_executions 기반 중복 실행 방지, `pai workflow run/resume`. 기존 승인 흐름과 병행하는 추가 경로로 구현(기존 경로 무변경) | 완료 |
| 9 | Proactive Assistant | Event sources, Scheduler, Deduplication, Quiet hours, Notification preferences | 계획됨 |
| 10 | Skill Store | Local skill package, Install/update/remove, Security audit, Version compatibility, Optional signature | 계획됨 |

각 Phase의 완료 조건(Definition of Done)은 SPEC.md §23의 해당 Phase 절과 §25(공통 Definition of Done)를 함께 만족해야 한다.
