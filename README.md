# Personal AI OS

Mac mini에서 상시 실행되는, 로컬 우선(local-first) Personal AI OS입니다.
대화형 인터페이스에서 개인 지식 검색(RAG), 실시간 데이터 질의, 외부 서비스 Skill 실행,
코드베이스 개발, 승인 기반 실행/감사를 통합합니다.

전체 제품 명세는 [SPEC.md](SPEC.md), 에이전트 작업 규칙은 [AGENTS.md](AGENTS.md)를 참고하세요.

## 구성 요소

- `apps/api` — FastAPI 기반 Assistant API
- `apps/web` — Next.js Chat/Projects/Skills 등 웹 UI
- `apps/cli` — `pai` Python CLI
- `apps/telegram-bot` — Telegram 봇 클라이언트 (Web UI/CLI와 동일한 기능 제공)
- `personal_ai/` — Core 도메인 로직 (Orchestrator, Policy, Memory, Skill, Tool, MCP ...)
- `infra/compose/docker-compose.yml` — PostgreSQL+pgvector, Redis, Ollama

## 빠른 시작

```bash
cp .env.example .env
make setup
make dev        # PostgreSQL/Redis/Ollama 기동 + API + Web 개발 서버
make doctor      # 의존 서비스 상태 점검
```

API: http://localhost:8010/health
Web: http://localhost:3000

### Telegram 봇 (선택)

Web UI/`pai` CLI로 할 수 있는 모든 작업(채팅, 프로젝트/메모리/지식베이스, 스킬, 승인,
작업, 워크스페이스, 워크플로, 알림)을 Telegram에서도 그대로 사용할 수 있습니다.

1. [@BotFather](https://t.me/BotFather)에서 봇을 만들고 토큰을 발급받습니다.
2. [@userinfobot](https://t.me/userinfobot)으로 본인의 숫자 Telegram user id를 확인합니다.
3. `.env`에 다음을 추가합니다 (둘 다 필수 — 없으면 봇이 시작되지 않고, 지정된 사용자
   외에는 봇을 제어할 수 없습니다):
   ```
   TELEGRAM_BOT_TOKEN=<BotFather에서 받은 토큰>
   TELEGRAM_ALLOWED_USER_ID=<본인의 숫자 user id>
   ```
4. `make dev-telegram`으로 실행합니다. 봇에게 `/help`를 보내면 전체 명령 목록이 나옵니다.

## Roadmap

Phase별 구현 로드맵은 [docs/ROADMAP.md](docs/ROADMAP.md)와 SPEC.md §23을 참고하세요.
현재 진행 상태: **Phase 0 (Repository Bootstrap) / Phase 1 (Local Chat Vertical Slice)**
