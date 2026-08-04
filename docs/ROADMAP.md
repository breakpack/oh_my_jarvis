# Roadmap

> 이 문서는 [SPEC.md](../SPEC.md) §23(구현 Roadmap)을 표로 정리한 것이다. 각 Phase의 상세 구현 항목과 완료 조건은 SPEC.md §23을 최종 근거로 삼는다.

## 현재 상태

- **Phase 0 ~ Phase 5: 완료** (`feat/phase-0` ~ `feat/phase-5` 브랜치)
- **Phase 6 ~ Phase 10: 계획됨** — 각 Phase는 동일한 방식(오케스트레이션 병렬 개발 + `feat/phase-N` 브랜치)으로 이어서 진행한다.

## Phase 목록

| Phase | 이름 | 핵심 구현 항목 | 상태 |
|---|---|---|---|
| 0 | Repository Bootstrap | Monorepo, FastAPI, Next.js, CLI, PostgreSQL+pgvector, Redis, Alembic, OpenTelemetry 기본, Makefile, CI, AGENTS.md | 완료 |
| 1 | Local Chat Vertical Slice | Conversation/Message, Ollama Provider, SSE Streaming, Chat UI, CLI Chat, Local/Cloud 수동 선택, 기본 Audit | 완료 |
| 2 | Project and Memory | Project CRUD, Active Project, Memory CRUD, Conversation Summary, Explicit remember/forget, Memory policy | 완료 |
| 3 | Second Brain RAG | Native parser(pypdf, Docling은 교체 가능한 어댑터로 계획만), Chunking, Local embedding(bge-m3), Hybrid retrieval, Evidence UI, Knowledge CLI | 완료 |
| 4 | Skill SDK and Read-only Tools | Skill manifest, SKILL.md loader, Schema validation, Skill Registry/Resolver, MCP Adapter(실제 stdio 연동), github-issues-lookup/local-file-search Skill, calendar/notion Stub, Skill CLI | 완료 |
| 5 | Approval and Mutation | Policy Engine, Approval Manager(Argument hash 검증), Task CRUD(LOW_WRITE 자동), GitHub Issue 생성(MEDIUM, 승인+Rollback), Calendar/Notion/Email은 Phase4 Stub 유지 | 완료 |
| 6 | Development Agent | Workspace, Sandbox, Repository scan, Code search, Patch, Formatter/Linter/Test, Diff, OpenHands Adapter 평가 | 계획됨 |
| 7 | Browser Agent | Playwright Tool, Browser Use Adapter, Browser approval, Prompt injection guard | 계획됨 |
| 8 | Durable Workflow | LangGraph, PostgreSQL Checkpoint, Interrupt, Retry, Resume, Cancellation | 계획됨 |
| 9 | Proactive Assistant | Event sources, Scheduler, Deduplication, Quiet hours, Notification preferences | 계획됨 |
| 10 | Skill Store | Local skill package, Install/update/remove, Security audit, Version compatibility, Optional signature | 계획됨 |

각 Phase의 완료 조건(Definition of Done)은 SPEC.md §23의 해당 Phase 절과 §25(공통 Definition of Done)를 함께 만족해야 한다.
