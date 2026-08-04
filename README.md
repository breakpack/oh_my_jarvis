# Personal AI OS

Mac mini에서 상시 실행되는, 로컬 우선(local-first) Personal AI OS입니다.
대화형 인터페이스에서 개인 지식 검색(RAG), 실시간 데이터 질의, 외부 서비스 Skill 실행,
코드베이스 개발, 승인 기반 실행/감사를 통합합니다.

전체 제품 명세는 [SPEC.md](SPEC.md), 에이전트 작업 규칙은 [AGENTS.md](AGENTS.md)를 참고하세요.

## 구성 요소

- `apps/api` — FastAPI 기반 Assistant API
- `apps/web` — Next.js Chat/Projects/Skills 등 웹 UI
- `apps/cli` — `pai` Python CLI
- `personal_ai/` — Core 도메인 로직 (Orchestrator, Policy, Memory, Skill, Tool, MCP ...)
- `infra/compose/docker-compose.yml` — PostgreSQL+pgvector, Redis, Ollama

## 빠른 시작

```bash
cp .env.example .env
make setup
make dev        # PostgreSQL/Redis/Ollama 기동 + API + Web 개발 서버
make doctor      # 의존 서비스 상태 점검
```

API: http://localhost:8000/health
Web: http://localhost:3000

## Roadmap

Phase별 구현 로드맵은 [docs/ROADMAP.md](docs/ROADMAP.md)와 SPEC.md §23을 참고하세요.
현재 진행 상태: **Phase 0 (Repository Bootstrap) / Phase 1 (Local Chat Vertical Slice)**
